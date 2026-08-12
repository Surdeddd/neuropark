"""Оркестрация задачи по стадиям. Маршрут детерминированный, LLM только внутри провайдеров."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from nn.catalog import Catalog
from nn.errors import Exit, NnError
from nn.i18n import bi
from nn.model import Role
from nn.paths import state_dir
from nn.registry import Registry
from nn.resolve import Choice, resolve_role
from nn.run import Envelope, execute
from nn.worktree import create, finish

STAGE_ROLES = {
    "spec": "spec",
    "work": "mechanics",
    "cross-review": "review",
    "verdict": "core",
}
DEFAULT_PATTERN = ("spec", "work", "cross-review", "verdict")


@dataclass(frozen=True)
class StageResult:
    stage: str
    role: str
    provider: str
    envelope: Envelope
    text: str
    patch: str | None = None


def _read_output(envelope: Envelope) -> str:
    if not envelope.out:
        return ""
    path = Path(envelope.out)
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _role_for(stage: str, work_role: str) -> str:
    if stage not in STAGE_ROLES:
        raise NnError(Exit.BAD_DATA, f"неизвестная стадия {stage}")
    return work_role if stage == "work" else STAGE_ROLES[stage]


def _prompt_for(stage: str, task: str, spec: str, patches: list[str], reviews: list[str]) -> str:
    """Промпт стадии.

    Формулировка задачи попадает в КАЖДУЮ стадию. Иначе в паттернах без стадии
    spec (например quick) исполнитель получал пустую спеку и не понимал, что от
    него хотят — ловилось только живым прогоном 2026-08-12.
    """
    head = f"Задача: {task}"
    spec_block = f"\n\nСпека:\n{spec}" if spec.strip() else ""

    if stage == "spec":
        return (
            f"{head}\n\n"
            "Составь строгую спеку на 10-15 строк: цель, вход и выход, крайние случаи,"
            " критерий готовности. Без реализации, без кода."
        )
    if stage == "work":
        return (
            f"{head}{spec_block}\n\n"
            "Реализуй это в текущем рабочем каталоге: меняй файлы напрямую."
            " Не спрашивай подтверждений, не создавай коммитов."
        )
    if stage == "cross-review":
        joined = "\n\n---\n\n".join(patches) or "(патча нет — так и скажи в ревью)"
        return (
            f"{head}{spec_block}\n\nПатч:\n{joined}\n\n"
            "Отревьюй: что расходится с задачей, где баги, чего не хватает. Коротко и по делу."
        )
    reviews_text = "\n\n---\n\n".join(reviews) or "(ревью не было)"
    patch_text = "\n\n---\n\n".join(patches) or "(патча нет — так и скажи в вердикте)"
    return (
        f"{head}{spec_block}\n\nПатчи:\n{patch_text}\n\nРевью:\n{reviews_text}\n\n"
        "Вердикт: какой патч брать, что доработать, чего не хватает."
        " Ничего не применяй и не коммить."
    )


def _work_stage(
    *,
    catalog: Catalog,
    registry: Registry,
    role: Role,
    role_name: str,
    prompt: str,
    repo: Path,
    run_index: int,
    exhausted: frozenset[str],
    now: datetime,
) -> StageResult:
    choice = resolve_role(role_name, catalog=catalog, registry=registry, exhausted=exhausted)
    run_id = f"{int(now.timestamp())}-orch{run_index}-{choice.provider.id}"
    if not role.worktree:
        envelope = execute(choice, catalog=catalog, prompt=prompt, work_dir=str(repo), now=now)
        return StageResult(
            stage="work",
            role=role_name,
            provider=choice.provider.id,
            envelope=envelope,
            text=_read_output(envelope),
        )

    worktree = create(repo, run_id)
    try:
        envelope = execute(choice, catalog=catalog, prompt=prompt, work_dir=str(worktree), now=now)
        result = finish(repo, worktree, run_id)
    except BaseException:
        finish(repo, worktree, run_id)
        raise
    patch = str(result.patch) if result.patch else None
    return StageResult(
        stage="work",
        role=role_name,
        provider=choice.provider.id,
        envelope=envelope,
        text=_read_output(envelope),
        patch=patch,
    )


def orchestrate(
    task: str,
    *,
    catalog: Catalog,
    registry: Registry,
    repo: Path,
    pattern: str = "default",
    work_role: str = "mechanics",
    fanout: int = 1,
    exhausted: frozenset[str] = frozenset(),
    now: datetime | None = None,
) -> list[StageResult]:
    moment = now or datetime.now(UTC)
    stages = catalog.roles.patterns.get(pattern, DEFAULT_PATTERN if pattern == "default" else ())
    if not stages:
        known = ", ".join(sorted(catalog.roles.patterns)) or "только default"
        raise NnError(Exit.BAD_DATA, f"паттерн {pattern} не описан (есть: {known})")

    results: list[StageResult] = []
    spec_text = ""
    patches: list[str] = []
    reviews: list[str] = []
    authors: set[str] = set()

    for stage in stages:
        role_name = _role_for(stage, work_role)
        role = catalog.roles.roles.get(role_name)
        if role is None:
            raise NnError(Exit.NO_PROVIDER, f"роль {role_name} для стадии {stage} не описана")

        prompt = _prompt_for(stage, task, spec_text, patches, reviews)

        if stage == "work":
            for index in range(max(1, fanout)):
                item = _work_stage(
                    catalog=catalog,
                    registry=registry,
                    role=role,
                    role_name=role_name,
                    prompt=prompt,
                    repo=repo,
                    run_index=index,
                    exhausted=exhausted,
                    now=moment,
                )
                results.append(item)
                authors.add(catalog.providers[item.provider].vendor_name)
                if item.patch:
                    patches.append(Path(item.patch).read_text(encoding="utf-8", errors="replace"))
            continue

        exclude = frozenset(authors) if stage == "cross-review" else frozenset()
        choice: Choice = resolve_role(
            role_name,
            catalog=catalog,
            registry=registry,
            exclude_vendors=exclude,
            exhausted=exhausted,
        )
        envelope = execute(choice, catalog=catalog, prompt=prompt, work_dir=str(repo), now=moment)
        text = _read_output(envelope)
        results.append(
            StageResult(
                stage=stage,
                role=role_name,
                provider=choice.provider.id,
                envelope=envelope,
                text=text,
            )
        )
        if stage == "spec":
            spec_text = text
        elif stage == "cross-review":
            reviews.append(text)

    return results


def report(results: list[StageResult]) -> str:
    role_word = bi("role", "роль")
    outcome_word = bi("outcome", "исход")
    patch_word = bi("patch", "патч")
    not_applied = bi("NOT applied, merge is yours", "НЕ применён, мерж твой")

    lines = [bi("# Orchestration report", "# Отчёт оркестрации"), ""]
    for item in results:
        lines.append(f"## {item.stage} — {item.provider} ({role_word} {item.role})")
        lines.append(f"{outcome_word}: {item.envelope.outcome}")
        if item.patch:
            lines.append(f"{patch_word}: {item.patch} ({not_applied})")
        lines.append("")
        lines.append(item.text.strip() or bi("(empty)", "(пусто)"))
        lines.append("")
    return "\n".join(lines)


def save_report(results: list[StageResult], run_id: str) -> Path:
    path = state_dir() / "out" / f"{run_id}-orchestration.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report(results), encoding="utf-8")
    return path

"""Досье провайдеров, которые заполняются сами.

Главное отличие от ultra: здесь ничего не надо засевать руками. Движок читает
новые строки runs.jsonl от вотермарки, сжимает исходы в уроки по шаблонам и
дописывает их в dossiers/<provider>.md. LLM для этого не нужен.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from nn.paths import data_dir, state_dir
from nn.runlog import RunRecord, read_all

MAX_LINES = 40
AUTO_LEARN_AFTER = 20
OBSERVED = "## observed"
INSTRUCTIONS = "## instructions"

_NUMBERS = re.compile(r"\d+")
_PATHS = re.compile(r"(/[\w.\-/]+)")


@dataclass(frozen=True)
class Lesson:
    provider: str
    observed: str
    instruction: str | None


def dossier_dir() -> Path:
    path = state_dir() / "dossiers"
    path.mkdir(parents=True, exist_ok=True)
    return path


def watermark_path() -> Path:
    return state_dir() / "state.json"


def read_watermark() -> int:
    path = watermark_path()
    if not path.is_file():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 0
    return int(payload.get("dossier_watermark", 0))


def write_watermark(value: int) -> None:
    path = watermark_path()
    payload: dict[str, object] = {}
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
    payload["dossier_watermark"] = value
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def signature(stderr_tail: str) -> str:
    """Подпись ошибки без чисел и путей, чтобы повторы склеивались.

    Берётся ПОСЛЕДНЯЯ непустая строка: у питоновского трейсбека первая строка
    всегда «Traceback (most recent call last):», а суть — в последней. Проверено
    на реальном падении ben-voice 2026-08-12.
    """
    lines = [line.strip() for line in stderr_tail.splitlines() if line.strip()]
    last = lines[-1] if lines else ""
    without_paths = _PATHS.sub("<путь>", last)
    return _NUMBERS.sub("N", without_paths).lower()[:120]


def load_rules(root: Path | None = None) -> list[tuple[str, str]]:
    path = (root or data_dir()) / "dossier-rules.json"
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return [
        (str(rule["match"]).lower(), str(rule["instruction"]))
        for rule in payload.get("rules", [])
        if rule.get("match") and rule.get("instruction")
    ]


def distill(records: list[RunRecord], rules: list[tuple[str, str]]) -> list[Lesson]:
    """Уроки из исходов. Советы даём только по известным подписям, остальное — факты."""
    lessons: list[Lesson] = []
    by_provider: dict[str, list[RunRecord]] = {}
    for record in records:
        if record.outcome == "success":
            continue
        by_provider.setdefault(record.provider, []).append(record)

    for provider, items in sorted(by_provider.items()):
        empties: dict[str, int] = {}
        timeouts = 0
        signatures: dict[str, int] = {}
        last_seen: dict[str, str] = {}

        for record in items:
            if record.outcome == "empty":
                empties[record.capability] = empties.get(record.capability, 0) + 1
            if record.outcome == "timeout":
                timeouts += 1
            if record.stderr_tail.strip():
                sign = signature(record.stderr_tail)
                signatures[sign] = signatures.get(sign, 0) + 1
                last_seen[sign] = record.ts[:16]

        for capability, count in sorted(empties.items()):
            if count >= 3:
                lessons.append(
                    Lesson(
                        provider,
                        f"{capability}: пустой ответ {count} раза подряд",
                        "инлайн-промпт этому провайдеру не годится, подавай его через"
                        " {prompt_file} и проверяй, что вход не пустой",
                    )
                )

        if timeouts >= 2:
            longest = max((r.ms for r in items if r.outcome != "timeout"), default=0)
            target = max(1800, (longest // 1000) * 2)
            lessons.append(
                Lesson(
                    provider,
                    f"таймаут {timeouts} раза",
                    f"поднять timeout_s минимум до {target}",
                )
            )

        for sign, count in sorted(signatures.items(), key=lambda kv: (-kv[1], kv[0])):
            if count < 3:
                continue
            advice = next((text for needle, text in rules if needle in sign), None)
            lessons.append(
                Lesson(provider, f"«{sign}» × {count}, последний раз {last_seen[sign]}", advice)
            )

    return lessons


def render(existing: str, lessons: list[Lesson]) -> str:
    """Досье как два раздела. Переполнение вытесняет самые старые наблюдения."""
    observed: list[str] = []
    instructions: list[str] = []
    section = None
    for line in existing.splitlines():
        if line.startswith(OBSERVED):
            section = "observed"
            continue
        if line.startswith(INSTRUCTIONS):
            section = "instructions"
            continue
        if not line.strip():
            continue
        if section == "observed":
            observed.append(line)
        elif section == "instructions":
            instructions.append(line)

    for lesson in lessons:
        entry = f"- {lesson.observed}"
        if entry not in observed:
            observed.append(entry)
        if lesson.instruction:
            advice = f"- {lesson.instruction}"
            if advice not in instructions:
                instructions.append(advice)

    budget = MAX_LINES - len(instructions)
    if budget < 0:
        instructions = instructions[-MAX_LINES:]
        budget = 0
    observed = observed[-budget:] if budget else []

    parts = [OBSERVED, *observed, "", INSTRUCTIONS, *instructions, ""]
    return "\n".join(parts)


def learn(*, records: list[RunRecord] | None = None, rules_root: Path | None = None) -> list[str]:
    """Дистилляция новых записей в досье. Возвращает список задетых провайдеров."""
    all_records = records if records is not None else read_all()
    start = 0 if records is not None else read_watermark()
    fresh = all_records[start:]
    if not fresh:
        return []

    rules = load_rules(rules_root)
    lessons = distill(fresh, rules)
    touched: dict[str, list[Lesson]] = {}
    for lesson in lessons:
        touched.setdefault(lesson.provider, []).append(lesson)

    for provider, items in touched.items():
        path = dossier_dir() / f"{provider}.md"
        existing = path.read_text(encoding="utf-8") if path.is_file() else ""
        path.write_text(render(existing, items), encoding="utf-8")

    if records is None:
        write_watermark(len(all_records))
    return sorted(touched)


def instructions_for(provider: str) -> str:
    """Раздел instructions досье — то, что подмешивается в промпт."""
    path = dossier_dir() / f"{provider}.md"
    if not path.is_file():
        return ""
    lines: list[str] = []
    inside = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(INSTRUCTIONS):
            inside = True
            continue
        if line.startswith("## ") and inside:
            break
        if inside and line.strip():
            lines.append(line.lstrip("- ").strip())
    return "\n".join(lines)


def pending_count() -> int:
    """Сколько записей ещё не дистиллировано."""
    return max(0, len(read_all()) - read_watermark())


def should_auto_learn() -> bool:
    return pending_count() >= AUTO_LEARN_AFTER

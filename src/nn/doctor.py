from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from nn.catalog import Catalog
from nn.detect import run_detect
from nn.errors import NnError
from nn.paths import expand
from nn.registry import Registry
from nn.render import pick
from nn.runlog import RunRecord, read_all

KNOWN_VARS = {"in", "out", "out_base", "tmp", "dir", "prompt_file"}
_NAME_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_.]*)\}")


_STEP_REF_RE = re.compile(r"^\{step(\d+)\.out\}$")


@dataclass(frozen=True)
class Finding:
    severity: str
    subject: str
    message: str


def _ref_problem(ref: str, current_index: int) -> str | None:
    """Ссылка на вход шага валидна, только если это {input} или выход прошлого шага."""
    if ref == "{input}":
        return None
    match = _STEP_REF_RE.match(ref)
    if not match:
        return f"непонятная ссылка {ref} (допустимы {{input}} и {{stepN.out}})"
    if int(match.group(1)) >= current_index:
        return f"ссылка {ref} смотрит вперёд или на себя"
    return None


def check(
    catalog: Catalog,
    registry: Registry | None,
    *,
    runs: list[RunRecord] | None = None,
    system: str | None = None,
) -> list[Finding]:
    if registry is None:
        return [Finding("error", "registry", "реестра нет — сделай nn scan")]

    findings: list[Finding] = []
    used = {record.provider for record in (runs if runs is not None else read_all())}

    for provider in sorted(catalog.providers.values(), key=lambda p: p.id):
        host = catalog.hosts.get(provider.host) or catalog.hosts["local"]
        allowed = (
            KNOWN_VARS
            | set(provider.vars)
            | {f"host.paths.{key}" for key in host.paths}
        )
        for stage in ("pre", "run", "post"):
            template = pick(getattr(provider, stage), system=system)
            if template is None:
                if stage == "run" and not provider.adapter:
                    findings.append(Finding("error", provider.id, "нет шаблона run под текущую ОС"))
                continue
            for name in _NAME_RE.findall(template):
                if name not in allowed and not name.startswith("extra"):
                    findings.append(
                        Finding("error", provider.id, f"{stage}: неизвестная переменная {{{name}}}")
                    )

        for key, raw in provider.vars.items():
            try:
                path = Path(expand(raw))
            except NnError as exc:
                findings.append(Finding("error", provider.id, f"vars.{key}: {exc.message}"))
                continue
            if path.is_absolute() and not path.exists():
                findings.append(
                    Finding("error", provider.id, f"vars.{key}: путь {path} не существует")
                )

        for raw_file in provider.detect.get("files") or ():
            path = Path(str(raw_file)).expanduser()
            if not path.exists():
                findings.append(Finding("warn", provider.id, f"detect.files: {path} отсутствует"))

        if provider.capability not in catalog.capabilities:
            findings.append(
                Finding(
                    "warn",
                    provider.id,
                    f"capability {provider.capability} не описан в capabilities.json —"
                    " стыковка типов про него не знает",
                )
            )

        entry = registry.get(provider.id)
        if entry and entry.status == "needs-key":
            findings.append(Finding("warn", provider.id, f"статус needs-key: {entry.reason}"))
        if entry and entry.status == "stale":
            findings.append(Finding("warn", provider.id, f"статус stale: {entry.reason}"))
        if entry and entry.status == "ok" and provider.id not in used:
            findings.append(
                Finding(
                    "warn", provider.id, "доступен, но ни разу не запускался — мёртвый манифест?"
                )
            )

    by_capability: dict[str, list[str]] = {}
    for provider in catalog.providers.values():
        by_capability.setdefault(provider.capability, []).append(provider.id)
    for capability, ids in sorted(by_capability.items()):
        if not any(registry.ok(pid) for pid in ids):
            findings.append(
                Finding(
                    "error", capability, f"capability {capability}: ни одного доступного провайдера"
                )
            )

    for recipe in sorted(catalog.recipes.values(), key=lambda r: r.id):
        for index, step in enumerate(recipe.steps):
            if step.capability and step.capability not in catalog.capabilities:
                findings.append(
                    Finding(
                        "error",
                        recipe.id,
                        f"шаг {index}: capability {step.capability} не описан в capabilities.json",
                    )
                )
            for ref in (step.in_ref, *step.extra_in):
                if ref is None:
                    continue
                problem = _ref_problem(ref, index)
                if problem:
                    findings.append(Finding("error", recipe.id, f"шаг {index}: {problem}"))

    for bridge in sorted(catalog.bridges.values(), key=lambda b: b.id):
        if run_detect(bridge.detect).status != "ok":
            findings.append(
                Finding(
                    "warn",
                    bridge.id,
                    f"мостик {bridge.frm}→{bridge.to}: инструмент недоступен",
                )
            )

    return findings

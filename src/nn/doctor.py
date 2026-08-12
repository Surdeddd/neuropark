from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from nn.catalog import Catalog
from nn.detect import run_detect
from nn.errors import NnError
from nn.i18n import bi
from nn.orchestrate import STAGE_ROLES
from nn.paths import expand
from nn.registry import Registry
from nn.render import pick
from nn.runlog import RunRecord, read_all

KNOWN_VARS = {"in", "out", "out_base", "tmp", "dir", "prompt_file"}
SETTLED_RUNS = 10
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
        return bi(
            f"unclear reference {ref} (allowed: {{input}} and {{stepN.out}})",
            f"непонятная ссылка {ref} (допустимы {{input}} и {{stepN.out}})",
        )
    if int(match.group(1)) >= current_index:
        return bi(
            f"reference {ref} points forward or at itself",
            f"ссылка {ref} смотрит вперёд или на себя",
        )
    return None


def _check_roles(catalog: Catalog, registry: Registry) -> list[Finding]:
    """roles.json пишет adapt, но правят его руками — ссылки надо сверять."""
    findings: list[Finding] = []
    config = catalog.roles
    for name, role in sorted(config.roles.items()):
        unknown = [pid for pid in role.providers if pid not in catalog.providers]
        for pid in unknown:
            findings.append(
                Finding(
                    "error",
                    f"roles.{name}",
                    bi(
                        f"provider {pid} has no manifest",
                        f"провайдер {pid} не описан ни одним манифестом",
                    ),
                )
            )
        known = [pid for pid in role.providers if pid in catalog.providers]
        if known and not any(registry.ok(pid) for pid in known):
            findings.append(
                Finding(
                    "warn",
                    f"roles.{name}",
                    bi(
                        "no provider of this role is available",
                        "ни один провайдер роли сейчас не доступен",
                    ),
                )
            )

    for pattern, stages in sorted(config.patterns.items()):
        for stage in stages:
            needed = STAGE_ROLES.get(stage)
            if needed and needed not in config.roles:
                findings.append(
                    Finding(
                        "error",
                        f"patterns.{pattern}",
                        bi(
                            f"stage {stage} needs role {needed}, which is absent from roles",
                            f"стадия {stage} требует роль {needed}, а её в roles нет",
                        ),
                    )
                )
    return findings


def check(
    catalog: Catalog,
    registry: Registry | None,
    *,
    runs: list[RunRecord] | None = None,
    system: str | None = None,
) -> list[Finding]:
    if registry is None:
        return [
            Finding(
                "error", "registry", bi("no registry, run nn scan", "реестра нет — сделай nn scan")
            )
        ]

    findings: list[Finding] = []
    history = runs if runs is not None else read_all()
    used = {record.provider for record in history}
    settled = len(history) >= SETTLED_RUNS

    for provider in sorted(catalog.providers.values(), key=lambda p: p.id):
        host = catalog.hosts.get(provider.host) or catalog.hosts["local"]
        allowed = KNOWN_VARS | set(provider.vars) | {f"host.paths.{key}" for key in host.paths}
        for stage in ("pre", "run", "post"):
            template = pick(getattr(provider, stage), system=system)
            if template is None:
                if stage == "run" and not provider.adapter:
                    findings.append(
                        Finding(
                            "error",
                            provider.id,
                            bi("no run template for this OS", "нет шаблона run под текущую ОС"),
                        )
                    )
                continue
            for name in _NAME_RE.findall(template):
                if name not in allowed and not name.startswith("extra"):
                    findings.append(
                        Finding(
                            "error",
                            provider.id,
                            bi(
                                f"{stage}: unknown variable {{{name}}}",
                                f"{stage}: неизвестная переменная {{{name}}}",
                            ),
                        )
                    )

        for key, raw in provider.vars.items():
            try:
                path = Path(expand(raw))
            except NnError as exc:
                findings.append(Finding("error", provider.id, f"vars.{key}: {exc.message}"))
                continue
            if path.is_absolute() and not path.exists():
                findings.append(
                    Finding(
                        "error",
                        provider.id,
                        bi(
                            f"vars.{key}: path {path} does not exist",
                            f"vars.{key}: путь {path} не существует",
                        ),
                    )
                )

        for raw_file in provider.detect.get("files") or ():
            path = Path(str(raw_file)).expanduser()
            if not path.exists():
                findings.append(
                    Finding(
                        "warn",
                        provider.id,
                        bi(f"detect.files: {path} is missing", f"detect.files: {path} отсутствует"),
                    )
                )

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
            findings.append(
                Finding(
                    "warn",
                    provider.id,
                    bi(f"status needs-key: {entry.reason}", f"статус needs-key: {entry.reason}"),
                )
            )
        if entry and entry.status == "stale":
            findings.append(
                Finding(
                    "warn",
                    provider.id,
                    bi(f"status stale: {entry.reason}", f"статус stale: {entry.reason}"),
                )
            )
        if settled and entry and entry.status == "ok" and provider.id not in used:
            findings.append(
                Finding(
                    "warn",
                    provider.id,
                    bi(
                        "available but never run — a dead manifest?",
                        "доступен, но ни разу не запускался — мёртвый манифест?",
                    ),
                )
            )

    by_capability: dict[str, list[str]] = {}
    for provider in catalog.providers.values():
        by_capability.setdefault(provider.capability, []).append(provider.id)
    for capability, ids in sorted(by_capability.items()):
        if not any(registry.ok(pid) for pid in ids):
            findings.append(
                Finding(
                    "error",
                    capability,
                    bi(
                        f"capability {capability}: no available provider",
                        f"capability {capability}: ни одного доступного провайдера",
                    ),
                )
            )

    findings.extend(_check_roles(catalog, registry))

    for recipe in sorted(catalog.recipes.values(), key=lambda r: r.id):
        for index, step in enumerate(recipe.steps):
            if step.capability and step.capability not in catalog.capabilities:
                findings.append(
                    Finding(
                        "error",
                        recipe.id,
                        bi(
                            f"step {index}: capability {step.capability}"
                            " is absent from capabilities.json",
                            f"шаг {index}: capability {step.capability}"
                            " не описан в capabilities.json",
                        ),
                    )
                )
            for ref in (step.in_ref, *step.extra_in):
                if ref is None:
                    continue
                problem = _ref_problem(ref, index)
                if problem:
                    prefix = bi(f"step {index}", f"шаг {index}")
                    findings.append(Finding("error", recipe.id, f"{prefix}: {problem}"))

    for bridge in sorted(catalog.bridges.values(), key=lambda b: b.id):
        if run_detect(bridge.detect).status != "ok":
            findings.append(
                Finding(
                    "warn",
                    bridge.id,
                    bi(
                        f"bridge {bridge.frm}→{bridge.to}: tool unavailable",
                        f"мостик {bridge.frm}→{bridge.to}: инструмент недоступен",
                    ),
                )
            )

    return findings

"""Сборка roles.json под конкретную машину.

Детерминированно и без LLM: берём то, что скан признал доступным, и раскладываем
по ролям по rank и подсказкам roles из манифестов. Результат — обычный файл,
который можно и нужно править руками.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from nn.catalog import Catalog
from nn.paths import user_data_dir
from nn.registry import Registry

ROLE_ORDER = ("core", "spec", "mechanics", "frontend", "review", "scout")
WORKTREE_ROLES = {"mechanics", "frontend"}
PATTERNS = {
    "default": ("spec", "work", "cross-review", "verdict"),
    "quick": ("work", "verdict"),
}
COMMENT = (
    "Собрано nn adapt детерминированно из результатов скана. Правь руками:"
    " порядок в providers — это цепочка фолбэков роли."
)


@dataclass(frozen=True)
class RolePlan:
    providers: tuple[str, ...]
    worktree: bool


@dataclass(frozen=True)
class AdaptResult:
    roles: dict[str, RolePlan] = field(default_factory=dict)
    patterns: dict[str, tuple[str, ...]] = field(default_factory=lambda: dict(PATTERNS))

    def to_payload(self) -> dict[str, object]:
        return {
            "_comment": COMMENT,
            "roles": {
                name: {"providers": list(plan.providers), "worktree": plan.worktree}
                for name, plan in self.roles.items()
            },
            "patterns": {name: list(stages) for name, stages in self.patterns.items()},
        }


def _text_providers(catalog: Catalog, registry: Registry) -> list[str]:
    available = [
        provider
        for provider in catalog.providers.values()
        if provider.capability == "text" and registry.ok(provider.id)
    ]
    return [p.id for p in sorted(available, key=lambda p: (-p.rank, p.id))]


def build(catalog: Catalog, registry: Registry) -> AdaptResult:
    ranked = _text_providers(catalog, registry)
    roles: dict[str, RolePlan] = {}

    for role in ROLE_ORDER:
        hinted = [pid for pid in ranked if role in catalog.providers[pid].roles]
        chain = tuple(hinted + [pid for pid in ranked if pid not in hinted])
        if not chain:
            continue
        roles[role] = RolePlan(providers=chain, worktree=role in WORKTREE_ROLES)

    return AdaptResult(roles=roles)


def write(result: AdaptResult) -> Path:
    """Роли — личные данные, поэтому лежат рядом с личными манифестами, а не в стейте."""
    path = user_data_dir() / "roles.json"
    path.write_text(json.dumps(result.to_payload(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path

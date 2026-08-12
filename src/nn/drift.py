"""Что изменилось в парке с прошлого скана.

Никаких уведомлений и расписаний: скан запускает человек, а дрейф просто
показывается в выводе nn scan. Меньше инфраструктуры — меньше поводов ей сгнить.
"""

from __future__ import annotations

from dataclasses import dataclass

from nn.registry import Registry

TITLES = {
    "appeared": "появилось",
    "disappeared": "исчезло",
    "status": "сменился статус",
    "version": "обновилась версия",
}
ORDER = ("appeared", "disappeared", "status", "version")


@dataclass(frozen=True)
class DriftItem:
    kind: str  # appeared | disappeared | status | version
    provider: str
    detail: str


def compare(old: Registry | None, new: Registry) -> list[DriftItem]:
    """Первый скан дрейфом не считается: сравнивать не с чем."""
    if old is None:
        return []
    items: list[DriftItem] = []
    for pid, entry in sorted(new.entries.items()):
        was = old.entries.get(pid)
        if was is None:
            items.append(DriftItem("appeared", pid, f"новая нейронка, статус {entry.status}"))
            continue
        if was.status != entry.status:
            detail = f"{was.status} → {entry.status}"
            if entry.reason:
                detail += f" ({entry.reason})"
            items.append(DriftItem("status", pid, detail))
        elif was.version != entry.version and entry.version:
            items.append(DriftItem("version", pid, f"{was.version or '?'} → {entry.version}"))
    for pid in sorted(set(old.entries) - set(new.entries)):
        items.append(DriftItem("disappeared", pid, "манифест исчез из каталога"))
    return items


def format_drift(items: list[DriftItem]) -> str:
    if not items:
        return ""
    lines: list[str] = []
    for kind in ORDER:
        group = [item for item in items if item.kind == kind]
        if not group:
            continue
        lines.append(f"{TITLES[kind]}:")
        lines.extend(f"  {item.provider} — {item.detail}" for item in group)
    return "\n".join(lines)

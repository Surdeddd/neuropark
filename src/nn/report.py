from __future__ import annotations

from nn.catalog import Catalog
from nn.registry import Registry
from nn.resolve import Choice
from nn.runlog import RunRecord

LS_HEADERS = ["capability", "провайдер", "хост", "статус", "версия", "видели", "заметки"]
WHY_HEADERS = ["провайдер", "хост", "решение", "причина"]
STATS_HEADERS = ["провайдер", "вызовов", "успехов", "доля", "последний"]
DOCTOR_HEADERS = ["уровень", "объект", "что не так"]


def table(rows: list[list[str]], headers: list[str]) -> str:
    if not rows:
        return "(пусто)"
    grid = [headers, *rows]
    widths = [max(len(str(row[i])) for row in grid) for i in range(len(headers))]
    lines = [
        "  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(headers)),
        "  ".join("-" * width for width in widths),
    ]
    lines.extend(
        "  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)) for row in rows
    )
    return "\n".join(lines)


def ls_rows(
    catalog: Catalog, registry: Registry, *, capability: str | None = None
) -> list[list[str]]:
    rows: list[list[str]] = []
    for provider in sorted(
        catalog.providers.values(), key=lambda p: (p.capability, -p.rank, p.id)
    ):
        if capability and provider.capability != capability:
            continue
        entry = registry.get(provider.id)
        rows.append(
            [
                provider.capability,
                provider.id,
                provider.host,
                entry.status if entry else "не сканировался",
                (entry.version or "-") if entry else "-",
                (entry.last_seen or "-")[:10] if entry else "-",
                provider.notes[:60],
            ]
        )
    return rows


def why_rows(choice: Choice) -> list[list[str]]:
    rows = [[choice.provider.id, choice.host.id, "выбран", f"rank={choice.provider.rank}"]]
    if choice.bridge:
        rows.append([choice.bridge.id, "-", "мостик", f"{choice.bridge.frm}→{choice.bridge.to}"])
    if choice.manual:
        rows.append([choice.host.id, "-", "ручной", "хост auto=false — команда печатается"])
    rows.extend([[r.provider, "-", "отклонён", r.reason] for r in choice.rejected])
    return rows


def stats_rows(runs: list[RunRecord]) -> list[list[str]]:
    totals: dict[str, list[int]] = {}
    last: dict[str, str] = {}
    for record in runs:
        bucket = totals.setdefault(record.provider, [0, 0])
        bucket[0] += 1
        if record.outcome == "success":
            bucket[1] += 1
        if record.ts > last.get(record.provider, ""):
            last[record.provider] = record.ts
    rows: list[list[str]] = []
    for provider, (calls, wins) in sorted(totals.items(), key=lambda kv: -kv[1][0]):
        rows.append(
            [provider, str(calls), str(wins), f"{wins * 100 // calls}%", last[provider][:16]]
        )
    return rows

from __future__ import annotations

from nn.catalog import Catalog
from nn.i18n import bi
from nn.registry import Registry
from nn.resolve import Choice
from nn.runlog import RunRecord

LS_HEADERS = [
    "capability",
    bi("provider", "провайдер"),
    bi("host", "хост"),
    bi("status", "статус"),
    bi("version", "версия"),
    bi("seen", "видели"),
    bi("notes", "заметки"),
]
WHY_HEADERS = [
    bi("provider", "провайдер"),
    bi("host", "хост"),
    bi("decision", "решение"),
    bi("reason", "причина"),
]
STATS_HEADERS = [
    bi("provider", "провайдер"),
    bi("calls", "вызовов"),
    bi("wins", "успехов"),
    bi("rate", "доля"),
    bi("last", "последний"),
]
DOCTOR_HEADERS = [bi("level", "уровень"), bi("subject", "объект"), bi("problem", "что не так")]
QUOTA_HEADERS = [
    bi("provider", "провайдер"),
    bi("window", "окно"),
    bi("burned", "сожжено"),
    bi("state", "состояние"),
    bi("closes", "закроется"),
]
BURN_HEADERS = [bi("window", "окно"), "capability", bi("input", "вход"), bi("closes", "закроется")]
RECIPE_HEADERS = [bi("recipe", "рецепт"), bi("description", "описание"), bi("steps", "шаги")]
ROLE_HEADERS = [bi("role", "роль"), bi("provider chain", "цепочка провайдеров"), "worktree"]


def table(rows: list[list[str]], headers: list[str]) -> str:
    if not rows:
        return bi("(empty)", "(пусто)")
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
    for provider in sorted(catalog.providers.values(), key=lambda p: (p.capability, -p.rank, p.id)):
        if capability and provider.capability != capability:
            continue
        entry = registry.get(provider.id)
        rows.append(
            [
                provider.capability,
                provider.id,
                provider.host,
                entry.status if entry else bi("not scanned", "не сканировался"),
                (entry.version or "-") if entry else "-",
                (entry.last_seen or "-")[:10] if entry else "-",
                provider.notes[:60],
            ]
        )
    return rows


def why_rows(choice: Choice) -> list[list[str]]:
    rows = [
        [choice.provider.id, choice.host.id, bi("chosen", "выбран"), f"rank={choice.provider.rank}"]
    ]
    if choice.bridge:
        rows.append(
            [
                choice.bridge.id,
                "-",
                bi("bridge", "мостик"),
                f"{choice.bridge.frm}→{choice.bridge.to}",
            ]
        )
    if choice.manual:
        rows.append(
            [
                choice.host.id,
                "-",
                bi("manual", "ручной"),
                bi("host auto=false, command is printed", "команда печатается"),
            ]
        )
    rows.extend([[r.provider, "-", bi("rejected", "отклонён"), r.reason] for r in choice.rejected])
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

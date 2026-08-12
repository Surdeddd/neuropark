"""Очередь задач под простаивающую квоту: окно всё равно истечёт, пусть работает."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

from nn.errors import Exit, NnError
from nn.i18n import bi
from nn.paths import state_dir
from nn.quota import Window

SOON_HOURS = 1.0


@dataclass(frozen=True)
class BurnTask:
    ts: str
    capability: str
    input: str
    note: str = ""


def queue_path() -> Path:
    return state_dir() / "burn-queue.jsonl"


def enqueue(task: BurnTask) -> None:
    if not Path(task.input).expanduser().is_file():
        raise NnError(
            Exit.BAD_IO,
            bi(
                f"input {task.input} not found, not queueing it",
                f"вход {task.input} не найден — в очередь не кладу",
            ),
        )
    with queue_path().open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(task), ensure_ascii=False) + "\n")


def read_queue() -> list[BurnTask]:
    path = queue_path()
    if not path.is_file():
        return []
    tasks: list[BurnTask] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            tasks.append(BurnTask(**json.loads(line)))
        except (json.JSONDecodeError, TypeError):
            continue
    return tasks


def rewrite_queue(tasks: list[BurnTask]) -> None:
    payload = "".join(json.dumps(asdict(t), ensure_ascii=False) + "\n" for t in tasks)
    queue_path().write_text(payload, encoding="utf-8")


def idle_windows(
    windows: dict[str, Window], *, now: datetime, soon_hours: float = SOON_HOURS
) -> list[Window]:
    """Окна, которые скоро закроются неиспользованными либо вообще не начинались."""
    result: list[Window] = []
    for window in windows.values():
        if window.is_exhausted(now=now):
            continue
        if window.idle:
            result.append(window)
            continue
        closes = window.resets_at
        closing_soon = closes is not None and closes - now <= timedelta(hours=soon_hours)
        has_room = window.remaining is None or window.remaining > 0
        if closing_soon and has_room:
            result.append(window)
    return sorted(result, key=lambda w: w.provider)


def candidates(
    windows: dict[str, Window],
    tasks: list[BurnTask],
    provider_capability: dict[str, str],
    *,
    now: datetime,
) -> list[tuple[Window, BurnTask]]:
    """Пары «свободное окно — задача, которую оно закрывает»."""
    pairs: list[tuple[Window, BurnTask]] = []
    for window in idle_windows(windows, now=now):
        capability = provider_capability.get(window.provider)
        if capability is None:
            continue
        for task in tasks:
            if task.capability == capability:
                pairs.append((window, task))
    return pairs

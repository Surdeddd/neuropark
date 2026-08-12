"""Учёт квотных окон. Всё считается из runs.jsonl — руками ничего вводить не надо."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from nn.model import Provider
from nn.runlog import RunRecord

QUOTA_OUTCOME = "quota"


@dataclass(frozen=True)
class Window:
    provider: str
    window_h: float
    soft_cap: int | None
    calls: int
    window_started: datetime | None = None
    last_call: datetime | None = None
    exhausted_until: datetime | None = None

    @property
    def idle(self) -> bool:
        return self.calls == 0

    @property
    def remaining(self) -> int | None:
        if self.soft_cap is None:
            return None
        return max(0, self.soft_cap - self.calls)

    @property
    def resets_at(self) -> datetime | None:
        """Когда освободится место: окно отсчитывается от самого старого вызова в нём."""
        if self.window_started is None:
            return None
        return self.window_started + timedelta(hours=self.window_h)

    def is_exhausted(self, *, now: datetime) -> bool:
        if self.exhausted_until is not None and now < self.exhausted_until:
            return True
        return self.soft_cap is not None and self.calls >= self.soft_cap


def _parse(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def compute(
    providers: Mapping[str, Provider],
    runs: list[RunRecord],
    *,
    now: datetime,
) -> dict[str, Window]:
    """Окна только для провайдеров, объявивших window_h: без него сбрасывать счётчик нечем."""
    tracked = {pid: p for pid, p in providers.items() if p.window_h}
    if not tracked:
        return {}

    windows: dict[str, Window] = {}
    for pid, provider in tracked.items():
        window_h = float(provider.window_h or 0)
        edge = now - timedelta(hours=window_h)
        stamps: list[datetime] = []
        exhausted_until: datetime | None = None

        for record in runs:
            if record.provider != pid:
                continue
            moment = _parse(record.ts)
            if moment is None or moment < edge:
                continue
            stamps.append(moment)
            if record.outcome == QUOTA_OUTCOME:
                candidate = moment + timedelta(hours=window_h)
                if exhausted_until is None or candidate > exhausted_until:
                    exhausted_until = candidate

        windows[pid] = Window(
            provider=pid,
            window_h=window_h,
            soft_cap=provider.soft_cap_calls,
            calls=len(stamps),
            window_started=min(stamps) if stamps else None,
            last_call=max(stamps) if stamps else None,
            exhausted_until=exhausted_until,
        )
    return windows


def exhausted_set(windows: Mapping[str, Window], *, now: datetime) -> frozenset[str]:
    return frozenset(pid for pid, window in windows.items() if window.is_exhausted(now=now))

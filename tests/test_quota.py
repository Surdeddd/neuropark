from datetime import UTC, datetime, timedelta

from nn.model import Provider
from nn.quota import Window, compute, exhausted_set
from nn.runlog import RunRecord

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def prov(pid: str, *, window_h: float | None = 5, soft_cap: int | None = 3) -> Provider:
    return Provider(
        id=pid,
        capability="text",
        kind="agent",
        detect={"bin": "echo"},
        io_in=("text",),
        io_out="text",
        notes="n",
        source=f"providers/{pid}.json",
        run={"": "true"},
        window_h=window_h,
        soft_cap_calls=soft_cap,
    )


def rec(provider: str, *, outcome: str = "success", minutes_ago: int = 10) -> RunRecord:
    ts = (NOW - timedelta(minutes=minutes_ago)).isoformat()
    return RunRecord(
        ts=ts,
        run_id=f"{ts}-{provider}",
        provider=provider,
        capability="text",
        host="local",
        in_type="text",
        out=None,
        exit_code=0,
        outcome=outcome,
        ms=10,
        stderr_tail="",
    )


def test_provider_without_window_has_no_quota():
    windows = compute({"free": prov("free", window_h=None, soft_cap=None)}, [], now=NOW)
    assert windows == {}


def test_counts_only_calls_inside_window():
    runs = [rec("a", minutes_ago=30), rec("a", minutes_ago=60), rec("a", minutes_ago=400)]
    windows = compute({"a": prov("a")}, runs, now=NOW)
    assert windows["a"].calls == 2


def test_soft_cap_marks_exhausted():
    runs = [rec("a", minutes_ago=i * 10) for i in range(3)]
    windows = compute({"a": prov("a", soft_cap=3)}, runs, now=NOW)
    assert windows["a"].calls == 3
    assert windows["a"].is_exhausted(now=NOW) is True
    assert "a" in exhausted_set(windows, now=NOW)


def test_below_soft_cap_is_not_exhausted():
    runs = [rec("a", minutes_ago=10)]
    windows = compute({"a": prov("a", soft_cap=3)}, runs, now=NOW)
    assert windows["a"].is_exhausted(now=NOW) is False


def test_quota_outcome_sets_exhausted_until_window_end():
    runs = [rec("a", outcome="quota", minutes_ago=60)]
    windows = compute({"a": prov("a", window_h=5, soft_cap=None)}, runs, now=NOW)
    window = windows["a"]
    assert window.exhausted_until is not None
    # окно 5 часов от момента отказа: 11:00 + 5ч = 16:00
    assert window.exhausted_until == (NOW - timedelta(minutes=60)) + timedelta(hours=5)
    assert window.is_exhausted(now=NOW) is True


def test_exhaustion_expires_after_window():
    runs = [rec("a", outcome="quota", minutes_ago=400)]
    windows = compute({"a": prov("a", window_h=5, soft_cap=None)}, runs, now=NOW)
    assert windows["a"].is_exhausted(now=NOW) is False
    assert exhausted_set(windows, now=NOW) == frozenset()


def test_soft_cap_without_window_hours_is_ignored():
    """Без window_h считать нечего: сбрасывать счётчик было бы нечем."""
    windows = compute({"a": prov("a", window_h=None, soft_cap=3)}, [rec("a")], now=NOW)
    assert windows == {}


def test_idle_window_is_reported():
    windows = compute({"a": prov("a")}, [], now=NOW)
    assert windows["a"].calls == 0
    assert windows["a"].idle is True


def test_window_remaining_calls():
    windows = compute({"a": prov("a", soft_cap=10)}, [rec("a"), rec("a")], now=NOW)
    assert windows["a"].remaining == 8


def test_remaining_is_none_without_soft_cap():
    windows = compute({"a": prov("a", soft_cap=None)}, [rec("a")], now=NOW)
    assert windows["a"].remaining is None


def test_window_resets_at_returns_end_of_oldest_call_window():
    runs = [rec("a", minutes_ago=120)]
    windows = compute({"a": prov("a", window_h=5)}, runs, now=NOW)
    assert windows["a"].resets_at == (NOW - timedelta(minutes=120)) + timedelta(hours=5)


def test_empty_window_resets_at_is_none():
    windows = compute({"a": prov("a")}, [], now=NOW)
    assert windows["a"].resets_at is None


def test_corrupt_timestamp_is_skipped():
    broken = rec("a")
    broken = RunRecord(**{**broken.__dict__, "ts": "не-дата"})
    windows = compute({"a": prov("a")}, [broken], now=NOW)
    assert windows["a"].calls == 0


def test_window_dataclass_is_serialisable():
    window = Window(provider="a", window_h=5, soft_cap=3, calls=1)
    assert window.provider == "a"
    assert window.is_exhausted(now=NOW) is False

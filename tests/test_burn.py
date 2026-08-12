from datetime import UTC, datetime, timedelta

import pytest

from nn.burn import BurnTask, candidates, enqueue, idle_windows, read_queue, rewrite_queue
from nn.errors import Exit, NnError
from nn.quota import Window

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def task(capability="image", input_path="/tmp/x.txt") -> BurnTask:
    return BurnTask(
        ts=NOW.isoformat(), capability=capability, input=input_path, note="ночной прожиг"
    )


def test_enqueue_and_read(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path))
    source = tmp_path / "prompt.txt"
    source.write_text("кадр", encoding="utf-8")
    enqueue(task(input_path=str(source)))
    queue = read_queue()
    assert len(queue) == 1
    assert queue[0].capability == "image"


def test_enqueue_rejects_missing_input(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path))
    with pytest.raises(NnError) as err:
        enqueue(task(input_path=str(tmp_path / "absent.txt")))
    assert err.value.code == Exit.BAD_IO


def test_read_queue_skips_corrupt_lines(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path))
    source = tmp_path / "prompt.txt"
    source.write_text("кадр", encoding="utf-8")
    enqueue(task(input_path=str(source)))
    with (tmp_path / "burn-queue.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{битый\n")
    assert len(read_queue()) == 1


def test_rewrite_queue_replaces_content(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path))
    source = tmp_path / "prompt.txt"
    source.write_text("кадр", encoding="utf-8")
    enqueue(task(input_path=str(source)))
    rewrite_queue([])
    assert read_queue() == []


def test_idle_window_is_candidate():
    windows = {"gen": Window(provider="gen", window_h=5, soft_cap=10, calls=0)}
    assert [w.provider for w in idle_windows(windows, now=NOW)] == ["gen"]


def test_exhausted_window_is_not_candidate():
    windows = {
        "gen": Window(provider="gen", window_h=5, soft_cap=2, calls=2),
    }
    assert idle_windows(windows, now=NOW) == []


def test_window_closing_soon_with_room_is_candidate():
    started = NOW - timedelta(hours=4, minutes=30)  # окно 5ч закроется через 30 минут
    windows = {
        "gen": Window(
            provider="gen", window_h=5, soft_cap=10, calls=1, window_started=started
        )
    }
    assert [w.provider for w in idle_windows(windows, now=NOW)] == ["gen"]


def test_window_with_time_left_is_not_urgent():
    started = NOW - timedelta(hours=1)
    windows = {
        "gen": Window(
            provider="gen", window_h=5, soft_cap=10, calls=1, window_started=started
        )
    }
    assert idle_windows(windows, now=NOW) == []


def test_candidates_pairs_window_with_matching_task():
    windows = {"gen": Window(provider="gen", window_h=5, soft_cap=10, calls=0)}
    pairs = candidates(windows, [task("image"), task("tts")], {"gen": "image"}, now=NOW)
    assert len(pairs) == 1
    assert pairs[0][0].provider == "gen"
    assert pairs[0][1].capability == "image"


def test_candidates_empty_without_matching_capability():
    windows = {"gen": Window(provider="gen", window_h=5, soft_cap=10, calls=0)}
    assert candidates(windows, [task("tts")], {"gen": "image"}, now=NOW) == []

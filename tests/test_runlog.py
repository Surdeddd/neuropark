from nn.runlog import RunRecord, append, last_success_map, read_all


def rec(provider="p", outcome="success", ts="2026-08-12T10:00:00+00:00") -> RunRecord:
    return RunRecord(
        ts=ts,
        run_id=f"{ts}-{provider}",
        provider=provider,
        capability="transcribe",
        host="local",
        in_type="audio",
        out="/tmp/out.srt",
        exit_code=0,
        outcome=outcome,
        ms=100,
        stderr_tail="",
    )


def test_append_then_read(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path))
    append(rec())
    append(rec(provider="q", outcome="crash"))
    records = read_all()
    assert [r.provider for r in records] == ["p", "q"]
    assert records[1].outcome == "crash"


def test_read_all_on_empty_state(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path))
    assert read_all() == []


def test_last_success_map_ignores_failures(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path))
    append(rec(provider="p", ts="2026-08-01T00:00:00+00:00"))
    append(rec(provider="p", ts="2026-08-11T00:00:00+00:00"))
    append(rec(provider="q", outcome="crash", ts="2026-08-12T00:00:00+00:00"))
    assert last_success_map() == {"p": "2026-08-11T00:00:00+00:00"}


def test_read_all_survives_corrupt_line(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path))
    append(rec())
    with (tmp_path / "runs.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{битый json\n")
    assert len(read_all()) == 1

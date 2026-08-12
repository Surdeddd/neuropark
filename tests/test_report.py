from nn.report import stats_rows, table
from nn.runlog import RunRecord


def rec(provider="p", outcome="success", ts="2026-08-12T10:00:00+00:00") -> RunRecord:
    return RunRecord(
        ts=ts,
        run_id="r",
        provider=provider,
        capability="transcribe",
        host="local",
        in_type="audio",
        out=None,
        exit_code=0,
        outcome=outcome,
        ms=10,
        stderr_tail="",
    )


def test_table_aligns_columns():
    out = table([["a", "bbb"], ["cccc", "d"]], headers=["h1", "h2"])
    lines = out.splitlines()
    assert lines[0].startswith("h1")
    assert "cccc" in lines[3]
    assert set(lines[1]) <= {"-", " "}


def test_table_handles_empty_rows():
    assert "пусто" in table([], headers=["h1"]).lower()


def test_stats_rows_counts_success_share():
    rows = stats_rows([rec(), rec(outcome="crash"), rec(provider="q")])
    by_provider = {row[0]: row for row in rows}
    assert by_provider["p"][1] == "2"
    assert by_provider["p"][2] == "1"
    assert by_provider["p"][3] == "50%"
    assert by_provider["q"][3] == "100%"


def test_stats_rows_empty():
    assert stats_rows([]) == []

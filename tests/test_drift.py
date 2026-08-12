from nn.drift import compare, format_drift
from nn.registry import Entry, Registry

TS = "2026-08-12T10:00:00+00:00"


def reg(entries: dict[str, tuple[str, str | None]]) -> Registry:
    return Registry(
        hostname="testbox",
        generated_at=TS,
        entries={
            pid: Entry(pid, "local", status, "", version, TS)
            for pid, (status, version) in entries.items()
        },
    )


def test_first_scan_is_not_drift():
    assert compare(None, reg({"a": ("ok", None)})) == []


def test_no_changes_no_drift():
    old = reg({"a": ("ok", "1.0")})
    assert compare(old, reg({"a": ("ok", "1.0")})) == []


def test_new_provider_appeared():
    items = compare(reg({}), reg({"a": ("ok", None)}))
    assert [i.kind for i in items] == ["appeared"]
    assert items[0].provider == "a"


def test_provider_disappeared():
    items = compare(reg({"a": ("ok", None)}), reg({}))
    assert [i.kind for i in items] == ["disappeared"]


def test_status_change_detected():
    items = compare(reg({"a": ("ok", None)}), reg({"a": ("missing", None)}))
    assert items[0].kind == "status"
    assert "ok → missing" in items[0].detail


def test_version_change_detected():
    items = compare(reg({"a": ("ok", "1.0")}), reg({"a": ("ok", "2.0")}))
    assert items[0].kind == "version"
    assert "1.0 → 2.0" in items[0].detail


def test_status_change_wins_over_version():
    items = compare(reg({"a": ("ok", "1.0")}), reg({"a": ("missing", "2.0")}))
    assert [i.kind for i in items] == ["status"]


def test_format_groups_by_kind():
    items = compare(reg({"a": ("ok", None), "b": ("ok", None)}), reg({"a": ("missing", None)}))
    text = format_drift(items)
    assert "сменился статус:" in text
    assert "исчезло:" in text
    assert "  a — ok → missing" in text


def test_format_empty_is_empty_string():
    assert format_drift([]) == ""

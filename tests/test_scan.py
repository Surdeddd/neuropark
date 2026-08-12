from datetime import UTC, datetime

from nn.catalog import Catalog
from nn.model import Host, Provider
from nn.registry import Entry, Registry
from nn.scan import scan

NOW = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)


def provider(pid: str, host: str = "local", **kw) -> Provider:
    defaults = dict(
        id=pid,
        capability="text",
        kind="agent",
        detect={"bin": "echo"},
        io_in=("text",),
        io_out="text",
        notes="фейк",
        source=f"providers/{pid}.json",
        host=host,
        run={"": "echo hi"},
    )
    defaults.update(kw)
    return Provider(**defaults)


def catalog(providers, hosts=None) -> Catalog:
    hosts = hosts or {"local": Host(id="local", kind="local")}
    return Catalog(
        providers={p.id: p for p in providers},
        hosts=hosts,
        capabilities={},
        types={},
        bridges={},
        recipes={},
    )


def test_scan_marks_ok_and_captures_version(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path))
    prov = provider("fake", version_cmd="echo v9")

    def runner(command, *, timeout):
        return (0, "v9\n", "") if "echo v9" in command else (0, "", "")

    reg = scan(catalog([prov]), runner=runner, now=NOW)
    assert reg.entries["fake"].status == "ok"
    assert reg.entries["fake"].version == "v9"
    assert reg.entries["fake"].last_seen == NOW.isoformat()


def test_scan_marks_missing_without_last_seen(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path))
    prov = provider("gone", detect={"bin": "nn-not-real-binary"})
    reg = scan(catalog([prov]), now=NOW)
    assert reg.entries["gone"].status == "missing"
    assert reg.entries["gone"].last_seen is None


def test_unreachable_host_yields_stale_and_keeps_previous_data(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path))
    hosts = {
        "local": Host(id="local", kind="local"),
        "winpc": Host(id="winpc", kind="ssh", addr="winpc-cc", probe="ssh winpc-cc true"),
    }
    prov = provider("comfy", host="winpc")
    previous = Registry(
        hostname="testbox",
        generated_at="2026-08-01T00:00:00+00:00",
        entries={"comfy": Entry("comfy", "winpc", "ok", "", "1.0", "2026-08-01T00:00:00+00:00")},
    )

    def runner(command, *, timeout):
        return (255, "", "connection refused")

    reg = scan(catalog([prov], hosts), runner=runner, now=NOW, previous=previous)
    entry = reg.entries["comfy"]
    assert entry.status == "stale"
    assert entry.version == "1.0"
    assert entry.last_seen == "2026-08-01T00:00:00+00:00"
    assert "недостижим" in entry.reason


def test_needs_key_status(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path))
    prov = provider("cloud", requires_key=("SOME_KEY",))
    reg = scan(catalog([prov]), now=NOW, env={})
    assert reg.entries["cloud"].status == "needs-key"


def test_unknown_host_is_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path))
    prov = provider("orphan", host="nowhere")
    reg = scan(catalog([prov]), now=NOW)
    assert reg.entries["orphan"].status == "missing"
    assert "не описан" in reg.entries["orphan"].reason


def test_host_probe_runs_once_per_host(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path))
    hosts = {
        "local": Host(id="local", kind="local"),
        "mini": Host(id="mini", kind="ssh", addr="mac-mini", probe="ssh mac-mini true"),
    }
    calls: list[str] = []

    def runner(command, *, timeout):
        calls.append(command)
        return (0, "", "")

    scan(
        catalog([provider("a", "mini"), provider("b", "mini")], hosts),
        runner=runner,
        now=NOW,
    )
    assert calls.count("ssh mac-mini true") == 1

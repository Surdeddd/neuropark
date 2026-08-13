import time
from datetime import UTC, datetime

from nn.catalog import Catalog
from nn.model import Capability, Host, Provider
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
        "gpu-box": Host(id="gpu-box", kind="ssh", addr="gpu-box", probe="ssh gpu-box true"),
    }
    prov = provider("comfy", host="gpu-box")
    previous = Registry(
        hostname="testbox",
        generated_at="2026-08-01T00:00:00+00:00",
        entries={"comfy": Entry("comfy", "gpu-box", "ok", "", "1.0", "2026-08-01T00:00:00+00:00")},
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
        "mini": Host(id="mini", kind="ssh", addr="remote-box", probe="ssh remote-box true"),
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
    assert calls.count("ssh remote-box true") == 1


def _many_providers(count: int, host_id: str = "local") -> Catalog:
    providers = {}
    for index in range(count):
        pid = f"p{index:02d}"
        providers[pid] = Provider(
            id=pid,
            capability="text",
            kind="tool",
            # python-стратегия идёт через runner, а bin проверяется питоном локально:
            # без этого фейковый runner в тестах вообще не звался.
            detect={"python": f"mod{index}"},
            io_in=("text",),
            io_out="text",
            notes="n",
            source=f"{pid}.json",
            host=host_id,
            run={"": "true > {out}"},
        )
    return Catalog(
        providers=providers,
        hosts={host_id: Host(id=host_id, kind="local")},
        capabilities={"text": Capability(name="text", in_types=("text",), out="text")},
        types={"text": ("txt",)},
        bridges={},
        recipes={},
    )


def test_registry_order_follows_the_catalog_not_the_finish_line():
    """Кто ответил первым, не должен менять порядок реестра: иначе дрейф врёт."""
    import random

    catalog = _many_providers(12)
    delays = {f"mod{index}": (0.02 if index % 3 else 0.0) for index in range(12)}

    def runner(command, *, timeout):
        for name, pause in delays.items():
            if name in command:
                time.sleep(pause + random.random() / 200)
        return (0, "", "")

    first = scan(catalog, runner=runner, env={}, workers=8)
    second = scan(catalog, runner=runner, env={}, workers=8)
    serial = scan(catalog, runner=runner, env={}, workers=1)
    assert list(first.entries) == list(catalog.providers)
    assert list(second.entries) == list(first.entries)
    assert list(serial.entries) == list(first.entries)


def test_parallel_and_serial_agree_on_every_status():
    catalog = _many_providers(9)

    def runner(command, *, timeout):
        return (1, "", "") if "mod4" in command else (0, "", "")

    parallel = scan(catalog, runner=runner, env={}, workers=8)
    serial = scan(catalog, runner=runner, env={}, workers=1)
    assert {pid: e.status for pid, e in parallel.entries.items()} == {
        pid: e.status for pid, e in serial.entries.items()
    }
    assert parallel.entries["p04"].status == "missing"


def test_parallel_scan_is_faster_than_serial_when_detects_wait():
    """Детекты ждут, а не считают: восемь потоков обязаны дать выигрыш."""
    catalog = _many_providers(8)

    def slow(command, *, timeout):
        time.sleep(0.15)
        return (0, "", "")

    started = time.monotonic()
    scan(catalog, runner=slow, env={}, workers=1)
    serial = time.monotonic() - started

    started = time.monotonic()
    scan(catalog, runner=slow, env={}, workers=8)
    parallel = time.monotonic() - started

    assert parallel * 2 < serial, f"serial={serial:.2f}s parallel={parallel:.2f}s"


def test_hosts_are_probed_once_each_even_in_parallel():
    """Probe спящей машины дорогой — на хост он должен быть один."""
    calls: list[str] = []
    providers = {
        f"p{index}": Provider(
            id=f"p{index}",
            capability="text",
            kind="tool",
            detect={"bin": "sh"},
            io_in=("text",),
            io_out="text",
            notes="n",
            source="s.json",
            host="far",
            run={"": "true > {out}"},
        )
        for index in range(5)
    }
    catalog = Catalog(
        providers=providers,
        hosts={
            "far": Host(id="far", kind="ssh", addr="far", auto=False, probe="probe-far"),
            "local": Host(id="local", kind="local"),
        },
        capabilities={"text": Capability(name="text", in_types=("text",), out="text")},
        types={"text": ("txt",)},
        bridges={},
        recipes={},
    )

    def runner(command, *, timeout):
        calls.append(command)
        return (0, "", "")

    scan(catalog, runner=runner, env={}, workers=8)
    assert calls.count("probe-far") == 1, calls


def test_one_broken_manifest_does_not_blind_the_whole_park(tmp_path, monkeypatch):
    """NnError из подстановки переменных раньше обрывал скан целиком."""
    monkeypatch.delenv("NN_NO_SUCH_VARIABLE", raising=False)
    good = Provider(
        id="good",
        capability="text",
        kind="tool",
        detect={"bin": "sh"},
        io_in=("text",),
        io_out="text",
        notes="n",
        source="good.json",
        host="local",
        run={"": "true > {out}"},
    )
    broken = Provider(
        id="broken",
        capability="text",
        kind="tool",
        detect={"python": "anything"},
        io_in=("text",),
        io_out="text",
        notes="n",
        source="broken.json",
        host="local",
        run={"": "true > {out}"},
        vars={"py": "$NN_NO_SUCH_VARIABLE/bin/python3"},
    )
    catalog = Catalog(
        providers={"good": good, "broken": broken},
        hosts={"local": Host(id="local", kind="local")},
        capabilities={"text": Capability(name="text", in_types=("text",), out="text")},
        types={"text": ("txt",)},
        bridges={},
        recipes={},
    )

    registry = scan(catalog, runner=lambda command, *, timeout: (0, "", ""), env={}, workers=8)
    assert registry.entries["good"].status == "ok"
    assert registry.entries["broken"].status == "missing"
    assert registry.entries["broken"].reason

from pathlib import Path

from nn.catalog import Catalog, load_catalog
from nn.doctor import check
from nn.model import Bridge, Capability, Host, Provider
from nn.registry import Entry, Registry
from nn.runlog import RunRecord

ROOT = Path(__file__).resolve().parents[1]

LOCAL = Host(id="local", kind="local")


def prov(pid="p", **kw) -> Provider:
    defaults = dict(
        id=pid,
        capability="transcribe",
        kind="model",
        detect={"bin": "echo"},
        io_in=("audio",),
        io_out="srt",
        notes="n",
        source=f"providers/{pid}.json",
        run={"": "tool -f {in} -o {out}"},
    )
    defaults.update(kw)
    return Provider(**defaults)


def cat(providers, caps=None, bridges=None) -> Catalog:
    default_caps = {"transcribe": Capability("transcribe", ("audio",), "srt")}
    return Catalog(
        providers={p.id: p for p in providers},
        hosts={"local": LOCAL},
        capabilities=default_caps if caps is None else caps,
        types={"audio": ("wav",), "srt": ("srt",)},
        bridges=bridges or {},
        recipes={},
    )


def reg(statuses) -> Registry:
    return Registry(
        hostname="testbox",
        generated_at="2026-08-12T10:00:00+00:00",
        entries={
            pid: Entry(pid, "local", status, "причина", None, "2026-08-12T10:00:00+00:00")
            for pid, status in statuses.items()
        },
    )


def test_reports_broken_var_path(tmp_path):
    provider = prov(
        vars={"model": str(tmp_path / "absent.bin")},
        run={"": "tool -m {model} -f {in} -o {out}"},
    )
    findings = check(cat([provider]), reg({"p": "ok"}), runs=[])
    assert any("absent.bin" in f.message and f.severity == "error" for f in findings)


def test_reports_unknown_template_variable():
    provider = prov(run={"": "tool --flag {mystery}"})
    findings = check(cat([provider]), reg({"p": "ok"}), runs=[])
    assert any("mystery" in f.message for f in findings)


def test_extra_variables_are_allowed():
    provider = prov(run={"": "tool {in} {extra0} {out}"})
    findings = check(cat([provider]), reg({"p": "ok"}), runs=[])
    assert not any("extra0" in f.message for f in findings)


def test_reports_capability_without_available_provider():
    findings = check(cat([prov()]), reg({"p": "missing"}), runs=[])
    assert any("transcribe" in f.message and "ни одного" in f.message for f in findings)


def test_reports_capability_missing_from_capabilities_json():
    provider = prov(capability="lipsync")
    findings = check(cat([provider], caps={}), reg({"p": "ok"}), runs=[])
    assert any("lipsync" in f.message and f.severity == "warn" for f in findings)


def test_reports_needs_key():
    findings = check(cat([prov()]), reg({"p": "needs-key"}), runs=[])
    assert any("needs-key" in f.message for f in findings)


def test_reports_stale():
    findings = check(cat([prov()]), reg({"p": "stale"}), runs=[])
    assert any("stale" in f.message for f in findings)


def other_run(provider: str = "кто-то-другой") -> RunRecord:
    return RunRecord(
        ts="2026-08-12T10:00:00+00:00",
        run_id="r",
        provider=provider,
        capability="text",
        host="local",
        in_type="text",
        out=None,
        exit_code=0,
        outcome="success",
        ms=10,
        stderr_tail="",
    )


def test_never_used_provider_is_silent_on_fresh_install():
    """На свежей установке «ни разу не запускался» — норма, а не находка."""
    findings = check(cat([prov()]), reg({"p": "ok"}), runs=[])
    assert not any("ни разу не запускался" in f.message for f in findings)


def test_reports_never_used_provider_on_settled_install():
    history = [other_run() for _ in range(10)]
    findings = check(cat([prov()]), reg({"p": "ok"}), runs=history)
    assert any("ни разу не запускался" in f.message for f in findings)


def test_reports_bridge_with_absent_tool():
    bridge = Bridge("b", "video", "audio", {"bin": "nn-not-real"}, {"": "true"}, "wav")
    findings = check(cat([prov()], bridges={"b": bridge}), reg({"p": "ok"}), runs=[])
    assert any(f.subject == "b" for f in findings)


def test_reports_missing_run_template_for_os():
    provider = prov(run={"win": "tool.exe"})
    findings = check(cat([provider]), reg({"p": "ok"}), runs=[], system="Darwin")
    assert any("под текущую ОС" in f.message and f.severity == "error" for f in findings)


def test_clean_catalog_has_no_errors(tmp_path):
    model = tmp_path / "m.bin"
    model.write_text("x", encoding="utf-8")
    provider = prov(vars={"model": str(model)}, run={"": "tool -m {model} -f {in} -o {out}"})
    findings = check(cat([provider]), reg({"p": "ok"}), runs=[])
    assert [f for f in findings if f.severity == "error"] == []


def test_missing_registry_is_single_error():
    findings = check(cat([prov()]), None, runs=[])
    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert "nn scan" in findings[0].message


def test_empty_park_is_a_warning_not_an_error(tmp_path, monkeypatch):
    """На машине без инструментов каталог цел: doctor обязан дать warn и exit 0.

    Пойман CI: на пустом раннере doctor отдавал 7, и это читалось как «nn сломан».
    """
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    catalog = load_catalog(ROOT)
    empty = Registry(hostname="bare", generated_at="2026-08-12T00:00:00+00:00", entries={})
    findings = check(catalog, empty, runs=[])
    assert findings, "пустой парк должен быть замечен"
    absent = [f for f in findings if "provider available" in f.message or "доступного" in f.message]
    assert absent
    assert all(f.severity == "warn" for f in absent), [f for f in absent if f.severity != "warn"]


def test_remote_host_without_path_gets_a_warning(tmp_path, monkeypatch):
    """PATH у неинтерактивного ssh-шелла урезан — это стоит сказать до прогона."""
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    host = Host(id="gpu", kind="ssh", addr="gpu", auto=True, probe="true")
    provider = Provider(
        id="far",
        capability="text",
        kind="tool",
        detect={"bin": "x"},
        io_in=("text",),
        io_out="text",
        notes="n",
        source="far.json",
        host="gpu",
        run={"": "x > {out}"},
    )
    catalog = Catalog(
        providers={"far": provider},
        hosts={"gpu": host, "local": Host(id="local", kind="local")},
        capabilities={"text": Capability(name="text", in_types=("text",), out="text")},
        types={"text": ("txt",)},
        bridges={},
        recipes={},
    )
    registry = Registry(
        hostname="h",
        generated_at="2026-08-13T00:00:00+00:00",
        entries={"far": Entry("far", "gpu", "ok", "", None, "2026-08-13")},
    )
    findings = check(catalog, registry, runs=[])
    about_path = [f for f in findings if f.subject == "gpu" and "PATH" in f.message]
    assert about_path, findings
    assert about_path[0].severity == "warn"


def test_remote_host_with_path_and_probe_is_quiet(tmp_path, monkeypatch):
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    host = Host(
        id="gpu",
        kind="ssh",
        addr="gpu",
        auto=True,
        probe="ssh gpu true",
        env={"PATH": "/usr/bin:/bin"},
    )
    provider = Provider(
        id="far",
        capability="text",
        kind="tool",
        detect={"bin": "x"},
        io_in=("text",),
        io_out="text",
        notes="n",
        source="far.json",
        host="gpu",
        run={"": "x > {out}"},
    )
    catalog = Catalog(
        providers={"far": provider},
        hosts={"gpu": host, "local": Host(id="local", kind="local")},
        capabilities={"text": Capability(name="text", in_types=("text",), out="text")},
        types={"text": ("txt",)},
        bridges={},
        recipes={},
    )
    registry = Registry(
        hostname="h",
        generated_at="2026-08-13T00:00:00+00:00",
        entries={"far": Entry("far", "gpu", "ok", "", None, "2026-08-13")},
    )
    assert [f for f in check(catalog, registry, runs=[]) if f.subject == "gpu"] == []


def test_manual_host_is_not_nagged_about_path(tmp_path, monkeypatch):
    """У auto=false команда только печатается — PATH там не наша забота."""
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    host = Host(id="gpu", kind="ssh", addr="gpu", auto=False)
    provider = Provider(
        id="far",
        capability="text",
        kind="tool",
        detect={"bin": "x"},
        io_in=("text",),
        io_out="text",
        notes="n",
        source="far.json",
        host="gpu",
        run={"": "x > {out}"},
    )
    catalog = Catalog(
        providers={"far": provider},
        hosts={"gpu": host, "local": Host(id="local", kind="local")},
        capabilities={"text": Capability(name="text", in_types=("text",), out="text")},
        types={"text": ("txt",)},
        bridges={},
        recipes={},
    )
    registry = Registry(
        hostname="h",
        generated_at="2026-08-13T00:00:00+00:00",
        entries={"far": Entry("far", "gpu", "ok", "", None, "2026-08-13")},
    )
    assert [f for f in check(catalog, registry, runs=[]) if f.subject == "gpu"] == []


def _one_provider_catalog(host: Host) -> Catalog:
    provider = Provider(
        id="far",
        capability="text",
        kind="tool",
        detect={"bin": "x"},
        io_in=("text",),
        io_out="text",
        notes="n",
        source="far.json",
        host=host.id,
        run={"": "x > {out}"},
    )
    return Catalog(
        providers={"far": provider},
        hosts={host.id: host, "local": Host(id="local", kind="local")},
        capabilities={"text": Capability(name="text", in_types=("text",), out="text")},
        types={"text": ("txt",)},
        bridges={},
        recipes={},
    )


def _registry_with(status: str, reason: str = "") -> Registry:
    return Registry(
        hostname="h",
        generated_at="2026-08-13T00:00:00+00:00",
        entries={"far": Entry("far", "gpu", status, reason, None, None)},
    )


def test_empty_capability_blames_the_host_when_the_host_is_the_problem(tmp_path, monkeypatch):
    """«Инструмент установлен?» — неверный вопрос, когда до машины не дошёл ssh."""
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    catalog = _one_provider_catalog(
        Host(id="gpu", kind="ssh", addr="gpu", auto=True, probe="true", env={"PATH": "/bin"})
    )
    findings = check(catalog, _registry_with("stale", "хост не ответил"), runs=[])
    about = [f for f in findings if f.subject == "text"]
    assert about, findings
    assert "не ответили" in about[0].message or "did not answer" in about[0].message
    assert "установлен" not in about[0].message and "installed" not in about[0].message


def test_empty_capability_mentions_the_key_when_that_is_the_problem(tmp_path, monkeypatch):
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    catalog = _one_provider_catalog(Host(id="gpu", kind="local"))
    findings = check(catalog, _registry_with("needs-key", "нет ключа"), runs=[])
    about = [f for f in findings if f.subject == "text"]
    assert about, findings
    assert "ключа" in about[0].message or "key" in about[0].message


def test_empty_capability_still_asks_about_installation_when_it_is_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    catalog = _one_provider_catalog(Host(id="gpu", kind="local"))
    findings = check(catalog, _registry_with("missing", "бинаря нет"), runs=[])
    about = [f for f in findings if f.subject == "text"]
    assert about, findings
    assert "установлен" in about[0].message or "installed" in about[0].message

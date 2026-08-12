from nn.catalog import Catalog
from nn.doctor import check
from nn.model import Bridge, Capability, Host, Provider
from nn.registry import Entry, Registry
from nn.runlog import RunRecord

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

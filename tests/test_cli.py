import json

import pytest

from nn.cli import main
from nn.errors import Exit

LONG_SRT = "1\\n00:00:00,000 --> 00:00:01,000\\nдостаточно длинный текст вот такой\\n"

PROVIDER = {
    "id": "fake-srt",
    "capability": "transcribe",
    "kind": "model",
    "detect": {"bin": "printf"},
    "io": {"in": ["audio"], "out": "srt"},
    "run": f"printf '{LONG_SRT}' > {{out}}",
    "notes": "фейковый провайдер для тестов",
    "rank": 5,
}
CAPS = {
    "types": {"audio": ["wav"], "srt": ["srt"], "video": ["mp4"]},
    "capabilities": {"transcribe": {"in": ["audio", "video"], "out": "srt"}},
}


@pytest.fixture
def env(monkeypatch, tmp_path):
    data = tmp_path / "data"
    (data / "providers").mkdir(parents=True)
    (data / "hosts").mkdir(parents=True)
    (data / "providers" / "fake-srt.json").write_text(json.dumps(PROVIDER), encoding="utf-8")
    (data / "hosts" / "local.json").write_text(
        json.dumps({"id": "local", "kind": "local"}), encoding="utf-8"
    )
    (data / "capabilities.json").write_text(json.dumps(CAPS), encoding="utf-8")
    monkeypatch.setenv("NN_DATA", str(data))
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    return tmp_path


def test_ls_without_registry_returns_five(env, capsys):
    assert main(["ls"]) == int(Exit.REGISTRY_STALE)
    assert "nn scan" in capsys.readouterr().err


def test_scan_then_ls_shows_provider(env, capsys):
    assert main(["scan"]) == int(Exit.OK)
    assert main(["ls"]) == int(Exit.OK)
    out = capsys.readouterr().out
    assert "fake-srt" in out
    assert "ok" in out


def test_ls_json_is_machine_readable(env, capsys):
    main(["scan"])
    capsys.readouterr()
    assert main(["--json", "ls"]) == int(Exit.OK)
    payload = json.loads(capsys.readouterr().out)
    assert payload["entries"]["fake-srt"]["status"] == "ok"


def test_why_explains_choice(env, capsys):
    main(["scan"])
    assert main(["why", "transcribe"]) == int(Exit.OK)
    out = capsys.readouterr().out
    assert "fake-srt" in out
    assert "выбран" in out


def test_why_unknown_capability_is_two(env, capsys):
    main(["scan"])
    assert main(["why", "mesh"]) == int(Exit.NO_PROVIDER)


def test_run_produces_output_and_envelope(env, capsys):
    main(["scan"])
    capsys.readouterr()
    source = env / "a.wav"
    source.write_bytes(b"\x00")
    assert main(["run", "transcribe", str(source)]) == int(Exit.OK)
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["outcome"] == "success"
    assert envelope["out"].endswith(".srt")
    assert envelope["in"] == str(source)


def test_run_with_pin_to_unknown_provider_is_two(env, capsys):
    main(["scan"])
    source = env / "a.wav"
    source.write_bytes(b"\x00")
    assert main(["run", "transcribe", str(source), "--provider", "ghost"]) == int(Exit.NO_PROVIDER)


def test_run_unknown_input_extension_is_eight(env, capsys):
    main(["scan"])
    weird = env / "a.zzz"
    weird.write_bytes(b"\x00")
    assert main(["run", "transcribe", str(weird)]) == int(Exit.BAD_IO)


def test_run_missing_input_file_is_eight(env, capsys):
    main(["scan"])
    assert main(["run", "transcribe", str(env / "absent.wav")]) == int(Exit.BAD_IO)


def test_doctor_reports_ok_on_clean_catalog(env, capsys):
    main(["scan"])
    source = env / "a.wav"
    source.write_bytes(b"\x00")
    main(["run", "transcribe", str(source)])
    capsys.readouterr()
    assert main(["doctor"]) == int(Exit.OK)
    assert "error" not in capsys.readouterr().out


def test_doctor_without_registry_is_bad_data(env, capsys):
    assert main(["doctor"]) == int(Exit.BAD_DATA)
    assert "nn scan" in capsys.readouterr().out


def test_stats_counts_runs(env, capsys):
    main(["scan"])
    source = env / "a.wav"
    source.write_bytes(b"\x00")
    main(["run", "transcribe", str(source)])
    capsys.readouterr()
    assert main(["stats"]) == int(Exit.OK)
    out = capsys.readouterr().out
    assert "fake-srt" in out
    assert "100%" in out


def test_stats_without_runs_says_empty(env, capsys):
    main(["scan"])
    capsys.readouterr()
    assert main(["stats"]) == int(Exit.OK)
    assert "пусто" in capsys.readouterr().out.lower()


def test_no_command_prints_help(env, capsys):
    assert main([]) == int(Exit.OK)
    assert "каталог парка нейронок" in capsys.readouterr().out

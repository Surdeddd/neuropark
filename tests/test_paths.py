from pathlib import Path

from nn.errors import Exit, NnError
from nn.paths import data_dir, expand, state_dir


def test_state_dir_defaults_under_home(monkeypatch):
    monkeypatch.delenv("NN_STATE", raising=False)
    assert state_dir() == Path.home() / ".claude" / "nn"


def test_state_dir_honours_env(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path / "s"))
    assert state_dir() == tmp_path / "s"
    assert (tmp_path / "s").is_dir()


def test_data_dir_honours_env(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_DATA", str(tmp_path / "d"))
    assert data_dir() == tmp_path / "d"


def test_expand_resolves_home_and_env(monkeypatch):
    monkeypatch.setenv("MODELS", "/opt/models")
    assert expand("$MODELS/x.bin") == "/opt/models/x.bin"
    assert expand("~/m.bin") == str(Path.home() / "m.bin")


def test_expand_rejects_unset_env_var():
    try:
        expand("$NN_DEFINITELY_UNSET_VAR/x")
    except NnError as exc:
        assert exc.code == Exit.BAD_DATA
    else:
        raise AssertionError("ожидалась NnError")

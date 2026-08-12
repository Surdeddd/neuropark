from datetime import UTC, datetime, timedelta

import pytest

from nn.errors import Exit, NnError
from nn.registry import Entry, Registry, is_expired, load, registry_path, save


def make_reg(generated_at: str) -> Registry:
    return Registry(
        hostname="testbox",
        generated_at=generated_at,
        entries={"p": Entry("p", "local", "ok", "", "1.2.3", generated_at)},
    )


def test_save_and_load_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path))
    now = datetime.now(UTC).isoformat()
    path = save(make_reg(now))
    assert path == registry_path("testbox")
    loaded = load("testbox")
    assert loaded.entries["p"].version == "1.2.3"
    assert loaded.ok("p") is True


def test_load_without_file_raises_stale(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path))
    with pytest.raises(NnError) as err:
        load("absent-host")
    assert err.value.code == Exit.REGISTRY_STALE
    assert "nn scan" in err.value.message


def test_is_expired_after_thirty_days():
    old = (datetime.now(UTC) - timedelta(days=31)).isoformat()
    assert is_expired(make_reg(old), now=datetime.now(UTC)) is True
    fresh = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    assert is_expired(make_reg(fresh), now=datetime.now(UTC)) is False


def test_ok_is_false_for_missing_and_absent(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path))
    reg = Registry(
        hostname="testbox",
        generated_at=datetime.now(UTC).isoformat(),
        entries={"gone": Entry("gone", "local", "missing", "нет бинаря")},
    )
    assert reg.ok("gone") is False
    assert reg.ok("never-heard-of") is False

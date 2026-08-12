"""Роли — личные данные: лежат рядом с личными манифестами, а не в стейте."""

import json
from pathlib import Path

import pytest

from nn.adapt import AdaptResult, RolePlan, write
from nn.catalog import load_catalog, roles_path
from nn.errors import Exit, NnError
from nn.orchestrate import orchestrate

CAPS = {"types": {"text": ["txt"]}, "capabilities": {"text": {"in": ["text"], "out": "text"}}}


def make_bundle(root: Path) -> None:
    (root / "hosts").mkdir(parents=True, exist_ok=True)
    (root / "hosts" / "local.json").write_text(
        json.dumps({"id": "local", "kind": "local"}), encoding="utf-8"
    )
    (root / "capabilities.json").write_text(json.dumps(CAPS), encoding="utf-8")


def test_adapt_writes_next_to_personal_manifests(tmp_path, monkeypatch):
    monkeypatch.setenv("NN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    path = write(AdaptResult(roles={"core": RolePlan(("alpha",), False)}))
    assert path.parent == tmp_path / "home"
    assert json.loads(path.read_text(encoding="utf-8"))["roles"]["core"]["providers"] == ["alpha"]


def test_personal_roles_win_over_bundled(tmp_path, monkeypatch):
    bundle, home = tmp_path / "repo", tmp_path / "home"
    make_bundle(bundle)
    home.mkdir(parents=True)
    monkeypatch.setenv("NN_HOME", str(home))
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    (bundle / "roles.json").write_text(
        json.dumps({"roles": {"core": {"providers": ["bundled"]}}}), encoding="utf-8"
    )
    (home / "roles.json").write_text(
        json.dumps({"roles": {"core": {"providers": ["personal"]}}}), encoding="utf-8"
    )
    assert roles_path(bundle) == home / "roles.json"
    catalog = load_catalog(bundle, user_root=home)
    assert catalog.roles.roles["core"].providers == ("personal",)


def test_state_location_still_read_for_compatibility(tmp_path, monkeypatch):
    """Ранние версии писали roles.json в стейт — такие установки не должны сломаться."""
    bundle, home, state = tmp_path / "repo", tmp_path / "home", tmp_path / "state"
    make_bundle(bundle)
    home.mkdir(parents=True)
    state.mkdir(parents=True)
    monkeypatch.setenv("NN_HOME", str(home))
    monkeypatch.setenv("NN_STATE", str(state))
    (state / "roles.json").write_text(
        json.dumps({"roles": {"core": {"providers": ["from-state"]}}}), encoding="utf-8"
    )
    assert roles_path(bundle) == state / "roles.json"


def test_orchestrate_without_roles_tells_you_to_adapt(tmp_path, monkeypatch):
    """Регрессия: пользователь получал «роль spec не описана» и не знал, что делать."""
    bundle, home = tmp_path / "repo", tmp_path / "home"
    make_bundle(bundle)
    home.mkdir(parents=True)
    monkeypatch.setenv("NN_HOME", str(home))
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    catalog = load_catalog(bundle, user_root=home)
    assert catalog.roles.roles == {}

    from nn.registry import Registry

    registry = Registry(hostname="testbox", generated_at="2026-08-12T10:00:00+00:00", entries={})
    with pytest.raises(NnError) as err:
        orchestrate("что-нибудь", catalog=catalog, registry=registry, repo=tmp_path)
    assert err.value.code == Exit.NO_PROVIDER
    assert "nn adapt" in err.value.message

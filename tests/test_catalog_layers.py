"""Слои каталога: поставляемое в репозитории, личное у пользователя, личное перекрывает."""

import json
from pathlib import Path

from nn.catalog import load_catalog

BASE_PROVIDER = {
    "id": "shared-tool",
    "capability": "text",
    "kind": "agent",
    "detect": {"bin": "printf"},
    "io": {"in": ["text"], "out": "text"},
    "run": "printf bundled > {out}",
    "rank": 1,
    "notes": {"en": "bundled", "ru": "поставляемый"},
}
CAPS = {
    "types": {"text": ["txt"]},
    "capabilities": {"text": {"in": ["text"], "out": "text"}},
}


def write(root: Path, rel: str, payload: dict) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def make_bundle(root: Path) -> None:
    write(root, "capabilities.json", CAPS)
    write(root, "hosts/local.json", {"id": "local", "kind": "local"})
    write(root, "providers/shared-tool.json", BASE_PROVIDER)


def test_user_layer_adds_providers(tmp_path):
    bundle, personal = tmp_path / "repo", tmp_path / "home"
    make_bundle(bundle)
    write(
        personal,
        "providers/my-tool.json",
        dict(BASE_PROVIDER, id="my-tool", notes={"en": "mine", "ru": "мой"}),
    )
    catalog = load_catalog(bundle, user_root=personal)
    assert set(catalog.providers) == {"shared-tool", "my-tool"}


def test_user_layer_overrides_bundled_by_id(tmp_path):
    bundle, personal = tmp_path / "repo", tmp_path / "home"
    make_bundle(bundle)
    write(
        personal,
        "providers/shared-tool.json",
        dict(BASE_PROVIDER, rank=99, run="printf personal > {out}"),
    )
    catalog = load_catalog(bundle, user_root=personal)
    assert catalog.providers["shared-tool"].rank == 99
    assert "personal" in catalog.providers["shared-tool"].run[""]


def test_user_layer_can_add_hosts(tmp_path):
    bundle, personal = tmp_path / "repo", tmp_path / "home"
    make_bundle(bundle)
    write(personal, "hosts/gpu.json", {"id": "gpu", "kind": "ssh", "addr": "gpu", "auto": False})
    catalog = load_catalog(bundle, user_root=personal)
    assert set(catalog.hosts) == {"local", "gpu"}


def test_user_layer_can_extend_capabilities(tmp_path):
    bundle, personal = tmp_path / "repo", tmp_path / "home"
    make_bundle(bundle)
    write(
        personal,
        "capabilities.json",
        {"types": {"mesh": ["glb"]}, "capabilities": {"mesh": {"in": ["image"], "out": "mesh"}}},
    )
    catalog = load_catalog(bundle, user_root=personal)
    assert "mesh" in catalog.capabilities
    assert "text" in catalog.capabilities
    assert "glb" in catalog.types["mesh"]


def test_user_layer_can_add_recipes_and_bridges(tmp_path):
    bundle, personal = tmp_path / "repo", tmp_path / "home"
    make_bundle(bundle)
    write(
        personal,
        "recipes/mine.json",
        {"id": "mine", "description": "личный", "steps": [{"capability": "text"}]},
    )
    write(
        personal,
        "bridges/txt-to-text.json",
        {
            "id": "txt-to-text",
            "from": "text",
            "to": "text",
            "detect": {"bin": "cp"},
            "run": "cp {in} {out}",
            "out_ext": "txt",
        },
    )
    catalog = load_catalog(bundle, user_root=personal)
    assert "mine" in catalog.recipes
    assert "txt-to-text" in catalog.bridges


def test_missing_user_layer_is_not_an_error(tmp_path):
    bundle = tmp_path / "repo"
    make_bundle(bundle)
    catalog = load_catalog(bundle, user_root=tmp_path / "does-not-exist")
    assert set(catalog.providers) == {"shared-tool"}


def test_bundle_alone_still_works(tmp_path):
    bundle = tmp_path / "repo"
    make_bundle(bundle)
    catalog = load_catalog(bundle, user_root=None)
    assert set(catalog.providers) == {"shared-tool"}

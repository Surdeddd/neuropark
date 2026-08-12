import json

import pytest

from nn.catalog import load_catalog
from nn.errors import Exit, NnError

PROVIDER = {
    "id": "fake-echo",
    "capability": "text",
    "kind": "agent",
    "detect": {"bin": "echo"},
    "io": {"in": ["text"], "out": "text"},
    "run": "echo hi",
    "notes": "фейк",
}


def write(root, rel, payload):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_catalog_reads_all_kinds(tmp_path):
    write(tmp_path, "providers/fake-echo.json", PROVIDER)
    write(tmp_path, "hosts/local.json", {"id": "local", "kind": "local"})
    write(
        tmp_path,
        "capabilities.json",
        {"types": {"text": ["txt"]}, "capabilities": {"text": {"in": ["text"], "out": "text"}}},
    )
    cat = load_catalog(tmp_path)
    assert set(cat.providers) == {"fake-echo"}
    assert cat.hosts["local"].kind == "local"
    assert cat.capabilities["text"].out == "text"


def test_load_catalog_rejects_id_filename_mismatch(tmp_path):
    write(tmp_path, "providers/other-name.json", PROVIDER)
    write(tmp_path, "hosts/local.json", {"id": "local", "kind": "local"})
    write(tmp_path, "capabilities.json", {"types": {}, "capabilities": {}})
    with pytest.raises(NnError) as err:
        load_catalog(tmp_path)
    assert err.value.code == Exit.BAD_DATA
    assert "имя файла" in err.value.message


def test_load_catalog_requires_local_host(tmp_path):
    write(tmp_path, "capabilities.json", {"types": {}, "capabilities": {}})
    with pytest.raises(NnError) as err:
        load_catalog(tmp_path)
    assert "hosts/local.json" in err.value.message


def test_load_catalog_reports_broken_json(tmp_path):
    write(tmp_path, "hosts/local.json", {"id": "local", "kind": "local"})
    write(tmp_path, "capabilities.json", {"types": {}, "capabilities": {}})
    (tmp_path / "providers").mkdir()
    (tmp_path / "providers" / "broken.json").write_text("{нет", encoding="utf-8")
    with pytest.raises(NnError) as err:
        load_catalog(tmp_path)
    assert "невалидный JSON" in err.value.message


def test_load_catalog_reads_repo_data():
    """Данные самого репозитория обязаны грузиться без ошибок."""
    cat = load_catalog()
    assert "transcribe" in cat.capabilities
    assert cat.capabilities["translate"].out == "same"
    assert cat.capabilities["subtitle-burn"].extra == ("srt",)

"""nn init: находит установленное и пишет валидные манифесты в личную директорию."""

import json
from pathlib import Path

import pytest

from nn.catalog import load_catalog
from nn.errors import Exit, NnError
from nn.init import (
    build_detect,
    build_manifest,
    discover,
    ensure_local_host,
    evaluate,
    load_priors,
    write_manifests,
)
from nn.schema import parse_provider

ROOT = Path(__file__).resolve().parents[1]

PRIOR_BIN = {
    "id": "fake-tool",
    "capability": "text",
    "kind": "agent",
    "probe": {"bin": "printf"},
    "io": {"in": ["text"], "out": "text"},
    "run": "printf hi > {out}",
    "notes": {"en": "fake", "ru": "фейк"},
}


def test_repo_priors_load():
    priors = load_priors(ROOT)
    assert priors
    assert all(prior.get("id") and prior.get("capability") for prior in priors)


def test_missing_priors_is_bad_data(tmp_path):
    with pytest.raises(NnError) as err:
        load_priors(tmp_path)
    assert err.value.code == Exit.BAD_DATA


def test_evaluate_finds_present_binary():
    candidate = evaluate(PRIOR_BIN)
    assert candidate.found is True
    assert candidate.manifest is not None


def test_evaluate_reports_absent_binary():
    prior = dict(PRIOR_BIN, probe={"bin": "nn-definitely-absent-binary"})
    candidate = evaluate(prior)
    assert candidate.found is False
    assert "nn-definitely-absent-binary" in candidate.reason


def test_model_glob_picks_biggest(tmp_path):
    small = tmp_path / "small.bin"
    big = tmp_path / "big.bin"
    small.write_bytes(b"x")
    big.write_bytes(b"x" * 100)
    prior = dict(PRIOR_BIN, probe={"bin": "printf", "model_glob": [str(tmp_path / "*.bin")]})
    assert evaluate(prior).model == str(big)


def test_model_prefer_beats_size(tmp_path):
    """У rnnoise профили равны по весу, но нужен именно речевой — размер тут не критерий."""
    (tmp_path / "big.rnnn").write_bytes(b"x" * 100)
    wanted = tmp_path / "sh.rnnn"
    wanted.write_bytes(b"x")
    prior = dict(
        PRIOR_BIN,
        probe={
            "bin": "printf",
            "model_glob": [str(tmp_path / "*.rnnn")],
            "model_prefer": ["sh.rnnn"],
        },
    )
    assert evaluate(prior).model == str(wanted)


def test_absent_model_makes_candidate_not_found(tmp_path):
    prior = dict(PRIOR_BIN, probe={"bin": "printf", "model_glob": [str(tmp_path / "*.nothing")]})
    candidate = evaluate(prior)
    assert candidate.found is False


def test_probe_becomes_detect():
    """Регрессия: init выкидывал probe и не создавал detect — манифесты выходили невалидными."""
    detect = build_detect({"bin": "whisper-cli", "model_glob": ["ignored"]}, "/models/a.bin")
    assert detect == {"bin": "whisper-cli", "files": ["/models/a.bin"]}


def test_generated_manifest_passes_schema():
    manifest = build_manifest(PRIOR_BIN, None)
    provider = parse_provider(manifest, source="generated")
    assert provider.id == "fake-tool"
    assert provider.detect


def test_every_repo_prior_generates_a_valid_manifest():
    """Приор, который нельзя превратить в валидный манифест, бесполезен."""
    for prior in load_priors(ROOT):
        manifest = build_manifest(prior, "/tmp/fake-model.bin")
        provider = parse_provider(manifest, source=str(prior.get("id")))
        assert provider.id == prior["id"]


def test_write_manifests_and_load_them(tmp_path, monkeypatch):
    """Найденное записывается манифестами, которые каталог потом читает.

    Приоры берутся синтетические: раньше тест брал репозиторные и требовал, чтобы
    на машине хоть что-то стояло. На пустом macOS-раннере не стояло ничего, и CI
    падал не из-за дефекта nn, а из-за железа под тестом.
    """
    monkeypatch.setenv("NN_HOME", str(tmp_path))
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    priors = tmp_path / "priors"
    priors.mkdir()
    (priors / "priors.json").write_text(json.dumps({"priors": [PRIOR_BIN]}), encoding="utf-8")

    found = [item for item in discover(root=priors) if item.found]
    assert found, "printf есть на любой POSIX-машине — приор обязан найтись"
    ensure_local_host()
    written = write_manifests(found)
    assert written

    catalog = load_catalog(ROOT, user_root=tmp_path)
    for item in found:
        assert item.id in catalog.providers


def test_discover_on_a_bare_machine_reports_absence_instead_of_failing(tmp_path, monkeypatch):
    """На машине без инструментов discover обязан вернуть список «не найдено», а не упасть."""
    monkeypatch.setenv("NN_HOME", str(tmp_path))
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    priors = tmp_path / "priors"
    priors.mkdir()
    absent = dict(PRIOR_BIN, id="ghost-tool", probe={"bin": "definitely-not-installed-xyz"})
    (priors / "priors.json").write_text(json.dumps({"priors": [absent]}), encoding="utf-8")

    items = discover(root=priors)
    assert [item.id for item in items] == ["ghost-tool"]
    assert not any(item.found for item in items)
    assert items[0].reason


def test_ensure_local_host_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("NN_HOME", str(tmp_path))
    first = ensure_local_host()
    payload = json.loads(first.read_text(encoding="utf-8"))
    payload["notes"] = "правка пользователя"
    first.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    second = ensure_local_host()
    assert second == first
    assert "правка пользователя" in second.read_text(encoding="utf-8")

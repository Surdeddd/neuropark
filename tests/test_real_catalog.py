"""Данные самого репозитория: схемы валидны, ссылки согласованы, личного внутри нет.

Поставляемый каталог намеренно универсален — в нём только инструменты без привязки
к путям конкретной машины. Всё, что требует модели или скрипта, приходит из priors.json
через `nn init` и живёт в личной директории пользователя.
"""

import json
from pathlib import Path

from nn.catalog import load_catalog
from nn.init import load_priors
from nn.render import pick

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_CAPABILITIES = {"transcribe", "tts", "text", "audio-clean", "compose", "subtitle-burn"}


def bundled() -> dict:
    """Только поставляемый каталог, без личного слоя пользователя."""
    return load_catalog(ROOT, user_root=None).providers


def test_real_catalog_loads():
    catalog = load_catalog(ROOT, user_root=None)
    assert catalog.providers
    assert "local" in catalog.hosts


def test_priors_cover_required_capabilities():
    """Гарантию покрытия даёт priors.json: bundled-каталог не знает путей к моделям."""
    covered = {str(prior.get("capability")) for prior in load_priors(ROOT)}
    assert covered >= REQUIRED_CAPABILITIES, REQUIRED_CAPABILITIES - covered


def test_every_bundled_provider_capability_is_declared():
    catalog = load_catalog(ROOT, user_root=None)
    for provider in catalog.providers.values():
        assert provider.capability in catalog.capabilities, provider.id


def test_every_bundled_provider_host_exists():
    catalog = load_catalog(ROOT, user_root=None)
    for provider in catalog.providers.values():
        assert provider.host in catalog.hosts, provider.id


def test_bundled_catalog_has_no_machine_specific_paths():
    """Ни путей пользователя, ни домашних папок: иначе на чужой машине это мусор."""
    offenders = []
    for path in sorted((ROOT / "providers").glob("*.json")):
        blob = path.read_text(encoding="utf-8")
        if "/Users/" in blob or "~/" in blob:
            offenders.append(path.name)
    assert offenders == [], offenders


def test_bundled_hosts_are_only_local():
    """Адреса чужих машин в публичном репозитории не место."""
    names = sorted(path.stem for path in (ROOT / "hosts").glob("*.json"))
    assert names == ["local"], names


def test_bundled_local_host_has_no_secrets():
    payload = json.loads((ROOT / "hosts" / "local.json").read_text(encoding="utf-8"))
    assert payload.get("env", {}) == {}


def test_every_bundled_provider_has_run_template_for_some_os():
    catalog = load_catalog(ROOT, user_root=None)
    for provider in catalog.providers.values():
        if provider.adapter:
            continue
        assert any(
            pick(provider.run, system=system) for system in ("Darwin", "Linux", "Windows")
        ), provider.id


def test_providers_with_own_interpreter_declare_their_module():
    """Дважды наступил: скрипт со своим venv обязан объявить detect.python,
    иначе скан считает его доступным до первого падения."""
    catalog = load_catalog(ROOT, user_root=None)
    offenders = [
        provider.id
        for provider in catalog.providers.values()
        if provider.vars.get("py") and not provider.detect.get("python")
    ]
    assert offenders == [], offenders


def test_all_bundled_notes_are_bilingual():
    monolingual = []
    for path in sorted((ROOT / "providers").glob("*.json")):
        notes = json.loads(path.read_text(encoding="utf-8")).get("notes")
        if not isinstance(notes, dict) or not notes.get("en") or not notes.get("ru"):
            monolingual.append(path.name)
    assert monolingual == []


def test_all_priors_notes_are_bilingual():
    monolingual = [
        str(prior.get("id"))
        for prior in load_priors(ROOT)
        if not isinstance(prior.get("notes"), dict)
        or not prior["notes"].get("en")
        or not prior["notes"].get("ru")
    ]
    assert monolingual == []


def test_examples_are_valid_manifests():
    """Примеры должны грузиться схемой, иначе они учат неправильному."""
    from nn.schema import parse_host, parse_provider

    for path in sorted((ROOT / "examples" / "providers").glob("*.json")):
        provider = parse_provider(json.loads(path.read_text(encoding="utf-8")), source=path.name)
        assert provider.id == path.stem
    for path in sorted((ROOT / "examples" / "hosts").glob("*.json")):
        host = parse_host(json.loads(path.read_text(encoding="utf-8")), source=path.name)
        assert host.id == path.stem


def test_bridges_declare_out_ext_and_detect():
    catalog = load_catalog(ROOT, user_root=None)
    assert catalog.bridges
    for bridge in catalog.bridges.values():
        assert bridge.out_ext
        assert bridge.detect

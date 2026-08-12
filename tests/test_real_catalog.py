"""Проверяет данные самого репозитория, а не подделки: схемы валидны, ссылки согласованы."""

from nn.catalog import load_catalog
from nn.render import pick

REQUIRED_CAPABILITIES = {"transcribe", "tts", "image", "embed", "audio-clean", "compose"}


def test_real_catalog_loads():
    catalog = load_catalog()
    assert catalog.providers
    assert "local" in catalog.hosts


def test_every_required_capability_has_a_provider():
    catalog = load_catalog()
    covered = {p.capability for p in catalog.providers.values()}
    assert covered >= REQUIRED_CAPABILITIES


def test_every_provider_capability_is_declared():
    catalog = load_catalog()
    for provider in catalog.providers.values():
        assert provider.capability in catalog.capabilities, provider.id


def test_every_provider_host_exists():
    catalog = load_catalog()
    for provider in catalog.providers.values():
        assert provider.host in catalog.hosts, provider.id


def test_no_absolute_user_paths_in_manifests():
    catalog = load_catalog()
    for provider in catalog.providers.values():
        blob = " ".join([*provider.vars.values(), *provider.run.values(), *provider.pre.values()])
        assert "/Users/" not in blob, provider.id


def test_every_provider_has_run_template_for_some_os():
    catalog = load_catalog()
    for provider in catalog.providers.values():
        if provider.adapter:
            continue
        assert any(
            pick(provider.run, system=system) for system in ("Darwin", "Linux", "Windows")
        ), provider.id


def test_remote_hosts_are_manual_in_phase_one():
    catalog = load_catalog()
    for host_id in ("winpc", "mac-mini"):
        assert catalog.hosts[host_id].auto is False


def test_api_key_never_lives_on_local_host():
    """Биллинг: на macbook подписка Max, ключ туда пускать нельзя."""
    catalog = load_catalog()
    assert catalog.hosts["local"].env == {}
    assert "ANTHROPIC_API_KEY" in catalog.hosts["mac-mini"].env


def test_secrets_are_declared_as_file_references_only():
    catalog = load_catalog()
    for host in catalog.hosts.values():
        for key, value in host.env.items():
            assert value.startswith("@file:"), f"{host.id}.{key} — секрет в открытом виде"


def test_bridges_declare_out_ext_and_detect():
    catalog = load_catalog()
    assert catalog.bridges
    for bridge in catalog.bridges.values():
        assert bridge.out_ext
        assert bridge.detect

import pytest

from nn.catalog import Catalog
from nn.errors import Exit, NnError
from nn.model import Bridge, Capability, Host, Provider
from nn.registry import Entry, Registry
from nn.resolve import resolve

TYPES = {"video": ("mp4",), "audio": ("wav",), "srt": ("srt",), "text": ("txt",)}
CAPS = {
    "transcribe": Capability("transcribe", ("video", "audio"), "srt"),
    "translate": Capability("translate", ("text", "srt"), "same"),
}
V2A = Bridge("video-to-audio", "video", "audio", {"bin": "echo"}, {"": "true"}, "wav")


def prov(pid, *, rank=0, host="local", io_in=("audio",), cap="transcribe") -> Provider:
    return Provider(
        id=pid,
        capability=cap,
        kind="model",
        detect={"bin": "echo"},
        io_in=io_in,
        io_out="srt",
        notes="n",
        source=f"providers/{pid}.json",
        host=host,
        rank=rank,
        run={"": "true"},
    )


def build(providers, hosts=None, statuses=None, bridges=None) -> tuple[Catalog, Registry]:
    hosts = hosts or {"local": Host(id="local", kind="local")}
    catalog = Catalog(
        providers={p.id: p for p in providers},
        hosts=hosts,
        capabilities=CAPS,
        types=TYPES,
        bridges=bridges or {},
        recipes={},
    )
    statuses = statuses or {}
    registry = Registry(
        hostname="testbox",
        generated_at="2026-08-12T10:00:00+00:00",
        entries={
            p.id: Entry(
                p.id, p.host, statuses.get(p.id, "ok"), "", None, "2026-08-12T10:00:00+00:00"
            )
            for p in providers
        },
    )
    return catalog, registry


def test_higher_rank_wins():
    catalog, registry = build([prov("low", rank=1), prov("high", rank=9)])
    choice = resolve("transcribe", catalog=catalog, registry=registry, in_type="audio")
    assert choice.provider.id == "high"
    assert choice.bridge is None
    assert choice.manual is False


def test_pin_overrides_rank():
    catalog, registry = build([prov("low", rank=1), prov("high", rank=9)])
    choice = resolve("transcribe", catalog=catalog, registry=registry, in_type="audio", pin="low")
    assert choice.provider.id == "low"


def test_pin_unknown_provider_is_no_provider():
    catalog, registry = build([prov("a")])
    with pytest.raises(NnError) as err:
        resolve("transcribe", catalog=catalog, registry=registry, in_type="audio", pin="ghost")
    assert err.value.code == Exit.NO_PROVIDER


def test_missing_status_is_rejected_with_reason():
    catalog, registry = build([prov("gone"), prov("live", rank=1)], statuses={"gone": "missing"})
    choice = resolve("transcribe", catalog=catalog, registry=registry, in_type="audio")
    assert choice.provider.id == "live"
    assert any(r.provider == "gone" and "missing" in r.reason for r in choice.rejected)


def test_provider_absent_from_registry_is_rejected():
    catalog, registry = build([prov("a")])
    registry = Registry(hostname="testbox", generated_at=registry.generated_at, entries={})
    with pytest.raises(NnError) as err:
        resolve("transcribe", catalog=catalog, registry=registry, in_type="audio")
    assert "nn scan" in err.value.message


def test_local_wins_over_remote_at_equal_rank():
    hosts = {
        "local": Host(id="local", kind="local"),
        "winpc": Host(id="winpc", kind="ssh", addr="w", auto=False),
    }
    catalog, registry = build([prov("remote", host="winpc"), prov("here")], hosts=hosts)
    choice = resolve("transcribe", catalog=catalog, registry=registry, in_type="audio")
    assert choice.provider.id == "here"


def test_manual_host_is_chosen_but_flagged():
    hosts = {
        "local": Host(id="local", kind="local"),
        "winpc": Host(id="winpc", kind="ssh", addr="w", auto=False),
    }
    catalog, registry = build([prov("remote", host="winpc")], hosts=hosts)
    choice = resolve("transcribe", catalog=catalog, registry=registry, in_type="audio")
    assert choice.manual is True


def test_bridge_inserted_when_input_type_mismatches():
    catalog, registry = build(
        [prov("audio-only", io_in=("audio",))], bridges={"video-to-audio": V2A}
    )
    choice = resolve("transcribe", catalog=catalog, registry=registry, in_type="video")
    assert choice.bridge is not None
    assert choice.bridge.id == "video-to-audio"


def test_no_bridge_means_bad_io():
    catalog, registry = build([prov("audio-only", io_in=("audio",))])
    with pytest.raises(NnError) as err:
        resolve("transcribe", catalog=catalog, registry=registry, in_type="video")
    assert err.value.code == Exit.BAD_IO


def test_out_type_resolves_same():
    catalog, registry = build([prov("tr", io_in=("srt",), cap="translate")])
    choice = resolve("translate", catalog=catalog, registry=registry, in_type="srt")
    assert choice.out_type == "srt"


def test_single_exhausted_provider_gives_quota_code():
    catalog, registry = build([prov("a")])
    with pytest.raises(NnError) as err:
        resolve(
            "transcribe",
            catalog=catalog,
            registry=registry,
            in_type="audio",
            exhausted=frozenset({"a"}),
        )
    assert err.value.code == Exit.QUOTA
    assert "a" in err.value.message
    assert "замены нет" in err.value.message


def test_exhausted_leader_refuses_instead_of_switching():
    """Ключевое правило спеки: молча подменять модель нельзя даже когда есть живой запас."""
    catalog, registry = build([prov("primary", rank=9), prov("spare", rank=1)])
    with pytest.raises(NnError) as err:
        resolve(
            "transcribe",
            catalog=catalog,
            registry=registry,
            in_type="audio",
            exhausted=frozenset({"primary"}),
        )
    assert err.value.code == Exit.QUOTA
    assert "primary" in err.value.message
    assert "spare" in err.value.message  # альтернативу обязаны назвать
    assert "--fallback" in err.value.message


def test_fallback_flag_allows_explicit_switch():
    catalog, registry = build([prov("primary", rank=9), prov("spare", rank=1)])
    choice = resolve(
        "transcribe",
        catalog=catalog,
        registry=registry,
        in_type="audio",
        exhausted=frozenset({"primary"}),
        allow_fallback=True,
    )
    assert choice.provider.id == "spare"
    assert any("квоты" in r.reason for r in choice.rejected)


def test_exhausted_non_leader_does_not_block_anything():
    catalog, registry = build([prov("primary", rank=9), prov("spare", rank=1)])
    choice = resolve(
        "transcribe",
        catalog=catalog,
        registry=registry,
        in_type="audio",
        exhausted=frozenset({"spare"}),
    )
    assert choice.provider.id == "primary"


def test_fallback_with_everything_exhausted_is_quota():
    catalog, registry = build([prov("a"), prov("b")])
    with pytest.raises(NnError) as err:
        resolve(
            "transcribe",
            catalog=catalog,
            registry=registry,
            in_type="audio",
            exhausted=frozenset({"a", "b"}),
            allow_fallback=True,
        )
    assert err.value.code == Exit.QUOTA


def test_unknown_capability_fails():
    catalog, registry = build([prov("a")])
    with pytest.raises(NnError) as err:
        resolve("mesh", catalog=catalog, registry=registry, in_type="audio")
    assert err.value.code == Exit.NO_PROVIDER


def test_no_run_template_for_os_is_rejected():
    provider = Provider(
        id="winonly",
        capability="transcribe",
        kind="model",
        detect={"bin": "echo"},
        io_in=("audio",),
        io_out="srt",
        notes="n",
        source="providers/winonly.json",
        run={"win": "tool.exe"},
    )
    catalog, registry = build([provider])
    with pytest.raises(NnError) as err:
        resolve(
            "transcribe", catalog=catalog, registry=registry, in_type="audio", system="Darwin"
        )
    assert "под текущую ОС" in err.value.message


def test_recent_success_breaks_tie():
    catalog, registry = build([prov("aaa"), prov("bbb")])
    choice = resolve(
        "transcribe",
        catalog=catalog,
        registry=registry,
        in_type="audio",
        last_success={"bbb": "2026-08-12T09:00:00+00:00"},
    )
    assert choice.provider.id == "bbb"

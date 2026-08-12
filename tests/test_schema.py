import pytest

from nn.errors import Exit, NnError
from nn.schema import parse_capabilities, parse_host, parse_provider

MINIMAL = {
    "id": "fake-echo",
    "capability": "text",
    "kind": "agent",
    "detect": {"bin": "echo"},
    "io": {"in": ["text"], "out": "text"},
    "run": "echo hi",
    "notes": "фейк для тестов",
}


def test_parse_provider_fills_defaults():
    prov = parse_provider(MINIMAL, source="providers/fake-echo.json")
    assert prov.host == "local"
    assert prov.rank == 0
    assert prov.timeout_s == 900
    assert prov.io_in == ("text",)
    assert prov.run == {"": "echo hi"}


def test_parse_provider_reads_out_ext_override():
    raw = dict(MINIMAL, io={"in": ["text"], "out": "audio", "out_ext": ".ogg"})
    prov = parse_provider(raw, source="x")
    assert prov.out_ext == "ogg"


def test_parse_provider_out_ext_defaults_to_none():
    assert parse_provider(MINIMAL, source="x").out_ext is None


def test_parse_provider_accepts_per_os_templates():
    raw = dict(MINIMAL, run={"darwin": "echo mac", "linux": "echo tux"})
    prov = parse_provider(raw, source="x")
    assert prov.run == {"darwin": "echo mac", "linux": "echo tux"}


@pytest.mark.parametrize(
    ("mutation", "fragment"),
    [
        ({"id": ""}, "id"),
        ({"kind": "神"}, "kind"),
        ({"detect": {}}, "detect"),
        ({"io": {"in": [], "out": "text"}}, "io.in"),
        ({"run": None, "adapter": None}, "run"),
        ({"adapter": "a.py"}, "adapter"),
        ({"notes": ""}, "notes"),
    ],
)
def test_parse_provider_rejects_bad_data(mutation, fragment):
    raw = dict(MINIMAL)
    raw.update(mutation)
    with pytest.raises(NnError) as err:
        parse_provider(raw, source="x")
    assert err.value.code == Exit.BAD_DATA
    assert fragment in err.value.message


def test_parse_provider_rejects_unknown_os_key():
    raw = dict(MINIMAL, run={"solaris": "echo"})
    with pytest.raises(NnError) as err:
        parse_provider(raw, source="x")
    assert "solaris" in err.value.message


def test_parse_host_defaults_auto_true_for_local():
    host = parse_host({"id": "local", "kind": "local"}, source="hosts/local.json")
    assert host.auto is True
    assert host.paths == {}


def test_parse_host_requires_addr_for_ssh():
    with pytest.raises(NnError) as err:
        parse_host({"id": "gpu-box", "kind": "ssh"}, source="hosts/gpu-box.json")
    assert "addr" in err.value.message


def test_parse_capabilities_returns_caps_and_types():
    caps, types = parse_capabilities(
        {
            "types": {"text": ["txt"], "srt": ["srt"]},
            "capabilities": {"translate": {"in": ["text", "srt"], "out": "same"}},
        }
    )
    assert caps["translate"].out == "same"
    assert types["srt"] == ("srt",)

from nn.bridge import find_bridge
from nn.model import Bridge

V2A = Bridge(
    id="video-to-audio",
    frm="video",
    to="audio",
    detect={"bin": "echo"},
    run={"": "ffmpeg -i {in} -vn -y {out}"},
    out_ext="wav",
)
A2T = Bridge(
    id="audio-to-text",
    frm="audio",
    to="text",
    detect={"bin": "echo"},
    run={"": "true"},
    out_ext="txt",
)
BROKEN = Bridge(
    id="aaa-broken-video-to-audio",
    frm="video",
    to="audio",
    detect={"bin": "nn-not-a-real-binary"},
    run={"": "true"},
    out_ext="wav",
)


def test_finds_direct_bridge():
    found = find_bridge("video", ("audio",), {"video-to-audio": V2A})
    assert found is not None
    assert found.id == "video-to-audio"


def test_returns_none_when_no_bridge():
    assert find_bridge("video", ("mesh",), {"video-to-audio": V2A}) is None


def test_never_chains_two_bridges():
    bridges = {"video-to-audio": V2A, "audio-to-text": A2T}
    assert find_bridge("video", ("text",), bridges) is None


def test_skips_bridge_whose_tool_is_absent():
    bridges = {"aaa-broken-video-to-audio": BROKEN, "video-to-audio": V2A}
    found = find_bridge("video", ("audio",), bridges)
    assert found is not None
    assert found.id == "video-to-audio"


def test_same_type_needs_no_bridge():
    assert find_bridge("audio", ("audio",), {"video-to-audio": V2A}) is None

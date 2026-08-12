import pytest

from nn.errors import Exit, NnError
from nn.iotypes import accepts, check_extra, ext_for, output_type, type_of
from nn.model import Capability

TYPES = {
    "video": ("mp4", "mov"),
    "audio": ("wav", "mp3"),
    "text": ("txt", "md"),
    "srt": ("srt", "vtt"),
}


def test_type_of_by_extension():
    assert type_of("a/b/clip.MP4", TYPES) == "video"
    assert type_of("x.srt", TYPES) == "srt"


def test_type_of_unknown_extension():
    with pytest.raises(NnError) as err:
        type_of("x.bin", TYPES)
    assert err.value.code == Exit.BAD_IO
    assert ".bin" in err.value.message


def test_type_of_without_extension():
    with pytest.raises(NnError) as err:
        type_of("Makefile", TYPES)
    assert err.value.code == Exit.BAD_IO


def test_output_type_resolves_same():
    translate = Capability("translate", ("text", "srt"), "same")
    assert output_type(translate, "srt") == "srt"
    assert output_type(translate, "text") == "text"


def test_output_type_plain():
    transcribe = Capability("transcribe", ("video", "audio"), "srt")
    assert output_type(transcribe, "video") == "srt"


def test_accepts():
    assert accepts(("video", "audio"), "audio") is True
    assert accepts(("video",), "audio") is False


def test_check_extra_requires_declared_types():
    burn = Capability("subtitle-burn", ("video",), "video", extra=("srt",))
    check_extra(burn, ("subs.srt",), TYPES)
    with pytest.raises(NnError) as missing:
        check_extra(burn, (), TYPES)
    assert missing.value.code == Exit.BAD_IO
    assert "srt" in missing.value.message
    with pytest.raises(NnError) as wrong:
        check_extra(burn, ("music.wav",), TYPES)
    assert wrong.value.code == Exit.BAD_IO


def test_check_extra_noop_without_requirement():
    plain = Capability("transcribe", ("audio",), "srt")
    check_extra(plain, (), TYPES)


def test_ext_for():
    assert ext_for("srt", TYPES) == "srt"
    with pytest.raises(NnError):
        ext_for("mesh", TYPES)

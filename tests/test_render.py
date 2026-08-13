import pytest

from nn.errors import Exit, NnError
from nn.model import Host, Provider
from nn.render import build_context, os_key, pick, render


def prov(**kw) -> Provider:
    defaults = dict(
        id="p",
        capability="transcribe",
        kind="model",
        detect={"bin": "echo"},
        io_in=("video",),
        io_out="srt",
        notes="n",
        source="providers/p.json",
        run={"": "tool -m {model} -f {in} -o {out}"},
        vars={"model": "~/Models/m.bin"},
    )
    defaults.update(kw)
    return Provider(**defaults)


def test_pick_prefers_exact_os():
    assert pick({"darwin": "mac", "": "any"}, system="Darwin") == "mac"
    assert pick({"": "any"}, system="Darwin") == "any"
    assert pick({"linux": "tux"}, system="Darwin") is None


def test_os_key_normalises():
    assert os_key("Darwin") == "darwin"
    assert os_key("Linux") == "linux"
    assert os_key("Windows") == "win"


def test_render_substitutes_known_names():
    assert render("a {x} b {y}", {"x": "1", "y": "2"}) == "a 1 b 2"


def test_render_rejects_unknown_name():
    with pytest.raises(NnError) as err:
        render("{nope}", {"x": "1"})
    assert err.value.code == Exit.BAD_DATA
    assert "nope" in err.value.message


def test_render_ignores_shell_braces():
    assert render("awk '{print $1}' {in}", {"in": "f.txt"}) == "awk '{print $1}' f.txt"


def test_render_supports_dotted_host_paths():
    assert render("{host.paths.models}/x", {"host.paths.models": "D:/m"}) == "D:/m/x"


def test_build_context_expands_vars_and_host_paths():
    host = Host(id="gpu-box", kind="ssh", addr="w", paths={"models": "D:/models"})
    ctx = build_context(
        prov(),
        host,
        in_path="a.mp4",
        out_path="/tmp/out/a.srt",
        tmp_prefix="/tmp/nn-123",
        work_dir="/repo",
    )
    assert ctx["in"] == "a.mp4"
    assert ctx["out"] == "/tmp/out/a.srt"
    assert ctx["out_base"] == "/tmp/out/a"
    assert ctx["tmp"] == "/tmp/nn-123"
    assert ctx["dir"] == "/repo"
    assert ctx["host.paths.models"] == "D:/models"
    assert ctx["model"].endswith("/Models/m.bin")
    assert "~" not in ctx["model"]


def test_paths_with_spaces_stay_one_argument():
    """`nn run transcribe "my clip.wav"` разваливался на два аргумента и падал 254."""
    command = render("tool -f {in} -o {out}", {"in": "/a/my clip.wav", "out": "/b/out file.srt"})
    assert command == "tool -f '/a/my clip.wav' -o '/b/out file.srt'"


def test_quote_in_a_filename_cannot_break_out_of_the_command():
    command = render("tool {in}", {"in": "/a/it's here.wav"})
    assert command == """tool '/a/it'"'"'s here.wav'"""
    assert ";" not in command.replace("/a/it's here.wav", "")


def test_a_filename_that_looks_like_an_injection_stays_data():
    nasty = "/tmp/x; rm -rf ~; echo pwned.wav"
    command = render("tool -f {in}", {"in": nasty})
    assert command == f"tool -f '{nasty}'"


def test_authors_own_variables_are_not_quoted():
    """В `vars` автор манифеста может держать набор флагов — кавычки их сломают."""
    command = render(
        "tool {flags} -m {model} {host.paths.models}",
        {"flags": "--fast --threads 8", "model": "/m/a.bin", "host.paths.models": "/data/models"},
    )
    assert command == "tool --fast --threads 8 -m /m/a.bin /data/models"


def test_suffix_after_a_placeholder_still_glues():
    """Шаблоны вида `{tmp}.wav` обязаны собираться в один путь."""
    command = render("ffmpeg -i {in} {tmp}.wav", {"in": "/a b.mp4", "tmp": "/t/run 1"})
    assert command == "ffmpeg -i '/a b.mp4' '/t/run 1'.wav"


def test_extra_inputs_are_quoted_too():
    command = render(
        "tool {in} {extra0} {extra1}", {"in": "/a a", "extra0": "/b b", "extra1": "/c"}
    )
    assert command == "tool '/a a' '/b b' /c"


def test_empty_value_stays_empty_not_two_quotes():
    assert render("tool {prompt_file}", {"prompt_file": ""}) == "tool "

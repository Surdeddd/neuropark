"""Сквозная проверка стыковки: мостик, три шага, ссылки на шаги. Без сети и моделей."""

import json
from pathlib import Path

import pytest

from nn.cli import main
from nn.errors import Exit

LONG = "текст достаточной длины для порога пустоты в классификаторе исходов"

FAKE_PROVIDERS = {
    "fake-transcribe": {
        "id": "fake-transcribe",
        "capability": "transcribe",
        "kind": "tool",
        "rank": 99,
        "detect": {"bin": "printf"},
        "io": {"in": ["audio"], "out": "srt"},
        "run": f"printf '1\\n00:00:00,000 --> 00:00:02,000\\n{LONG}\\n' > {{out}}",
        "notes": "фейк",
    },
    "fake-translate": {
        "id": "fake-translate",
        "capability": "translate",
        "kind": "tool",
        "rank": 99,
        "detect": {"bin": "sed"},
        "io": {"in": ["srt"], "out": "same"},
        "run": "sed 's/$/ [ru]/' {in} > {out}",
        "notes": "фейк",
    },
    "fake-burn": {
        "id": "fake-burn",
        "capability": "subtitle-burn",
        "kind": "tool",
        "rank": 99,
        "detect": {"bin": "cat"},
        "io": {"in": ["video"], "out": "video"},
        "run": "cat {in} {extra0} > {out}",
        "notes": "фейк",
    },
}
RECIPE = {
    "id": "fake-subs",
    "description": "фейковая цепочка",
    "steps": [
        {"capability": "transcribe"},
        {"capability": "translate"},
        {"capability": "subtitle-burn", "in": "{input}", "extra_in": ["{step1.out}"]},
    ],
}
CAPABILITIES = {
    "types": {"video": ["mp4"], "audio": ["wav"], "srt": ["srt"], "text": ["txt"]},
    "capabilities": {
        "transcribe": {"in": ["video", "audio"], "out": "srt"},
        "translate": {"in": ["srt", "text"], "out": "same"},
        "subtitle-burn": {"in": ["video"], "out": "video", "extra": ["srt"]},
    },
}
BRIDGE = {
    "id": "video-to-audio",
    "from": "video",
    "to": "audio",
    "detect": {"bin": "cp"},
    "run": "cp {in} {out}",
    "out_ext": "wav",
}


@pytest.fixture
def fake_root(monkeypatch, tmp_path):
    data = tmp_path / "data"
    for sub in ("providers", "hosts", "recipes", "bridges"):
        (data / sub).mkdir(parents=True)
    for pid, payload in FAKE_PROVIDERS.items():
        (data / "providers" / f"{pid}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
    (data / "hosts" / "local.json").write_text(
        json.dumps({"id": "local", "kind": "local"}), encoding="utf-8"
    )
    (data / "recipes" / "fake-subs.json").write_text(json.dumps(RECIPE), encoding="utf-8")
    (data / "bridges" / "video-to-audio.json").write_text(json.dumps(BRIDGE), encoding="utf-8")
    (data / "capabilities.json").write_text(json.dumps(CAPABILITIES), encoding="utf-8")
    monkeypatch.setenv("NN_DATA", str(data))
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    return tmp_path


def test_chain_bridges_video_then_runs_three_steps(fake_root, capsys):
    video = fake_root / "clip.mp4"
    video.write_bytes(b"fakevideo")
    assert main(["scan"]) == int(Exit.OK)
    capsys.readouterr()
    assert main(["recipe", "run", "fake-subs", str(video)]) == int(Exit.OK)
    envelopes = json.loads(capsys.readouterr().out)

    assert [e["capability"] for e in envelopes] == ["transcribe", "translate", "subtitle-burn"]
    # mp4 не принимается транскрайбером напрямую — мостик обязан был вставиться сам
    assert envelopes[0]["bridge"] == "video-to-audio"
    # третий шаг взял исходное видео, а не выход перевода
    assert envelopes[2]["in"] == str(video)
    translated = Path(envelopes[1]["out"])
    assert "[ru]" in translated.read_text(encoding="utf-8")


def test_recipe_ls_lists_recipes(fake_root, capsys):
    assert main(["recipe", "ls"]) == int(Exit.OK)
    out = capsys.readouterr().out
    assert "fake-subs" in out
    assert "transcribe → translate → subtitle-burn" in out


def test_unknown_recipe_is_bad_data(fake_root, capsys):
    main(["scan"])
    capsys.readouterr()
    assert main(["recipe", "run", "nope", str(fake_root / "clip.mp4")]) == int(Exit.BAD_DATA)


def test_recipe_stops_and_reports_failed_step(fake_root, capsys, monkeypatch):
    broken = dict(FAKE_PROVIDERS["fake-translate"], run="exit 7")
    (fake_root / "data" / "providers" / "fake-translate.json").write_text(
        json.dumps(broken), encoding="utf-8"
    )
    video = fake_root / "clip.mp4"
    video.write_bytes(b"fakevideo")
    main(["scan"])
    capsys.readouterr()
    code = main(["recipe", "run", "fake-subs", str(video)])
    envelopes = json.loads(capsys.readouterr().out)
    assert code == int(Exit.PROVIDER_FAILED)
    assert len(envelopes) == 2
    assert envelopes[1]["outcome"] == "crash"

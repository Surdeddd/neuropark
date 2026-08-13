"""Живые запуски на реальном железе, всё офлайн. Запуск: make smoke."""

import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.smoke

REPO = Path(__file__).resolve().parents[1]


def run_nn(args: list[str]) -> tuple[int, str]:
    done = subprocess.run(
        [str(REPO / "bin" / "nn"), *args],
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
        cwd=REPO,
    )
    return done.returncode, done.stdout


def make_tone(path: Path, seconds: int = 3) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def test_scan_finds_local_park():
    code, out = run_nn(["scan"])
    assert code == 0
    assert "реестр записан" in out


def test_transcribe_generated_tone(tmp_path):
    wav = tmp_path / "tone.wav"
    make_tone(wav)
    code, out = run_nn(["run", "transcribe", str(wav)])
    envelope = json.loads(out)
    # синусоида не речь: корректный исход — либо success с мусорными сабами, либо empty
    assert envelope["outcome"] in {"success", "empty"}
    assert envelope["provider"].startswith("whisper-cpp")


@pytest.mark.slow
def test_tts_one_phrase(tmp_path):
    """Медленный: холодный старт MLX плюс внутренняя сверка дублей — до 10 минут.

    Фраза намеренно длинная и естественная: на коротких обрывках внутренняя сверка TTS
    отбраковывает все дубли (замерено: 'проверка связи' даёт 0.57 при пороге выше).
    """
    source = tmp_path / "phrase.txt"
    source.write_text(
        "Сегодня проверяю каталог нейронок: транскрипт, озвучка и сборка видео"
        " работают из одной команды.",
        encoding="utf-8",
    )
    code, out = run_nn(["run", "tts", str(source)])
    envelope = json.loads(out)
    assert code == 0, envelope
    assert envelope["outcome"] == "success"
    assert envelope["out"].endswith(".ogg")


def test_video_input_inserts_bridge_for_real(tmp_path):
    """mp4 на входе транскрайбера: ffmpeg-мостик обязан отработать сам."""
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x240:d=3",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=3",
            "-shortest",
            str(clip),
        ],
        check=True,
        capture_output=True,
    )
    code, out = run_nn(["run", "transcribe", str(clip)])
    envelope = json.loads(out)
    assert envelope["bridge"] == "video-to-audio"
    assert envelope["outcome"] in {"success", "empty"}


def test_doctor_has_no_errors_on_real_catalog():
    code, out = run_nn(["doctor"])
    error_lines = [line for line in out.splitlines() if line.startswith("error")]
    assert error_lines == [], "\n".join(error_lines)
    assert code == 0


def make_silent_video(path: Path, seconds: int = 2) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=160x120:rate=10:duration={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=channel_layout=mono:sample_rate=16000:duration={seconds}",
            "-shortest",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )


def test_recipe_with_two_inputs_really_runs(tmp_path):
    """Шаг, берущий и {input}, и выход прошлого шага — на настоящем ffmpeg.

    README одно время утверждал, что рецепты с несколькими входами не реализованы,
    хотя `extra_in` работал. Теперь это под живым тестом, а не под честным словом.
    """
    data = tmp_path / "data"
    (data / "providers").mkdir(parents=True)
    (data / "hosts").mkdir(parents=True)
    (data / "recipes").mkdir(parents=True)

    for name in ("ffmpeg-compose", "ffmpeg-audio-clean"):
        source = REPO / "providers" / f"{name}.json"
        if source.is_file():
            (data / "providers" / f"{name}.json").write_text(
                source.read_text(encoding="utf-8"), encoding="utf-8"
            )
    (data / "hosts" / "local.json").write_text(
        json.dumps({"id": "local", "kind": "local"}), encoding="utf-8"
    )
    (data / "capabilities.json").write_text(
        (REPO / "capabilities.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    # Шаг 1 делает звук из видео, шаг 2 берёт видео из {input} и звук из шага 1.
    (data / "providers" / "extract-audio.json").write_text(
        json.dumps(
            {
                "id": "extract-audio",
                "capability": "audio-clean",
                "kind": "tool",
                "rank": 99,
                "detect": {"bin": "ffmpeg"},
                "io": {"in": ["video", "audio"], "out": "audio"},
                "run": "ffmpeg -nostdin -y -i {in} -vn -ar 16000 -ac 1 {out}",
                "notes": {"en": "audio out of a video", "ru": "звук из видео"},
            }
        ),
        encoding="utf-8",
    )
    (data / "recipes" / "reattach.json").write_text(
        json.dumps(
            {
                "id": "reattach",
                "description": {
                    "en": "pull the audio out, then put it back on the original video",
                    "ru": "вытащить звук и вернуть его на исходное видео",
                },
                "steps": [
                    {"capability": "audio-clean", "provider": "extract-audio"},
                    {
                        "capability": "compose",
                        "provider": "ffmpeg-compose",
                        "in": "{input}",
                        "extra_in": ["{step0.out}"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    clip = tmp_path / "clip.mp4"
    make_silent_video(clip)

    env = {"NN_DATA": str(data), "NN_STATE": str(tmp_path / "state"), "NN_LANG": "en"}
    scan = subprocess.run(
        [str(REPO / "bin" / "nn"), "scan"],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
        env={**os.environ, **env},
    )
    assert scan.returncode == 0, scan.stderr

    done = subprocess.run(
        [str(REPO / "bin" / "nn"), "recipe", "run", "reattach", str(clip)],
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
        env={**os.environ, **env},
    )
    assert done.returncode == 0, done.stdout + done.stderr

    envelopes = json.loads(done.stdout)
    assert len(envelopes) == 2, done.stdout
    assert [e["outcome"] for e in envelopes] == ["success", "success"]

    final = Path(envelopes[-1]["out"])
    assert final.is_file() and final.stat().st_size > 1000, final

    # У результата обязаны быть обе дорожки: значит второй вход дошёл.
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(final),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    kinds = [line.strip() for line in probe.stdout.splitlines() if line.strip()]
    assert "video" in kinds and "audio" in kinds, probe.stdout

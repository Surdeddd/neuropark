"""Живые запуски на реальном железе, всё офлайн. Запуск: make smoke."""

import json
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

    Фраза намеренно длинная и естественная: на коротких обрывках сверка ben-voice
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

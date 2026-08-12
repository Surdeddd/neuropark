from pathlib import Path

from nn.dossier import (
    MAX_LINES,
    distill,
    instructions_for,
    learn,
    load_rules,
    render,
    should_auto_learn,
    signature,
)
from nn.runlog import RunRecord, append


def rec(
    provider="p",
    outcome="crash",
    stderr="",
    capability="text",
    ms=1000,
    ts="2026-08-12T10:00:00+00:00",
) -> RunRecord:
    return RunRecord(
        ts=ts,
        run_id=f"{ts}-{provider}",
        provider=provider,
        capability=capability,
        host="local",
        in_type="text",
        out=None,
        exit_code=1,
        outcome=outcome,
        ms=ms,
        stderr_tail=stderr,
    )


def test_signature_strips_numbers_and_paths():
    a = signature("File /Users/x/scripts/a.py line 42: ModuleNotFoundError: no module named 'mlx'")
    b = signature("File /Users/y/other/b.py line 7: ModuleNotFoundError: no module named 'mlx'")
    assert a == b


def test_distill_ignores_successes():
    assert distill([rec(outcome="success")], []) == []


def test_three_empties_give_prompt_file_advice():
    lessons = distill([rec(outcome="empty") for _ in range(3)], [])
    assert len(lessons) == 1
    assert "пустой ответ" in lessons[0].observed
    assert lessons[0].instruction is not None
    assert "prompt_file" in lessons[0].instruction


def test_two_empties_are_not_enough():
    assert distill([rec(outcome="empty") for _ in range(2)], []) == []


def test_timeouts_advise_bigger_timeout():
    records = [rec(outcome="timeout"), rec(outcome="timeout"), rec(outcome="crash", ms=1_000_000)]
    lessons = distill(records, [])
    advice = [
        lesson for lesson in lessons if lesson.instruction and "timeout_s" in lesson.instruction
    ]
    assert advice
    assert "2000" in advice[0].instruction


def test_repeated_signature_becomes_observation():
    records = [rec(stderr="connection refused by host") for _ in range(3)]
    lessons = distill(records, [])
    assert any("connection refused" in lesson.observed for lesson in lessons)


def test_known_signature_gets_instruction_from_rules():
    rules = [("connection refused", "хост не поднят: проверь probe")]
    records = [rec(stderr="connection refused by host") for _ in range(3)]
    lessons = distill(records, rules)
    advice = "хост не поднят: проверь probe"
    assert [lesson for lesson in lessons if lesson.instruction == advice]


def test_unknown_signature_stays_fact_without_advice():
    records = [rec(stderr="какая-то невиданная ошибка") for _ in range(3)]
    lessons = distill(records, [])
    signature_lessons = [lesson for lesson in lessons if "невиданная" in lesson.observed]
    assert signature_lessons
    assert signature_lessons[0].instruction is None


def test_render_creates_both_sections():
    from nn.dossier import Lesson

    out = render("", [Lesson("p", "наблюдение", "совет")])
    assert "## observed" in out
    assert "- наблюдение" in out
    assert "## instructions" in out
    assert "- совет" in out


def test_render_does_not_duplicate_entries():
    from nn.dossier import Lesson

    first = render("", [Lesson("p", "наблюдение", "совет")])
    second = render(first, [Lesson("p", "наблюдение", "совет")])
    assert second.count("- наблюдение") == 1
    assert second.count("- совет") == 1


def test_render_caps_total_lines():
    from nn.dossier import Lesson

    lessons = [Lesson("p", f"наблюдение {i}", None) for i in range(80)]
    out = render("", lessons)
    body = [line for line in out.splitlines() if line.startswith("- ")]
    assert len(body) <= MAX_LINES
    # вытесняются самые старые, свежие остаются
    assert "наблюдение 79" in out
    assert "наблюдение 0" not in out


def test_learn_writes_dossier_file(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path))
    records = [rec(outcome="empty") for _ in range(3)]
    touched = learn(records=records)
    assert touched == ["p"]
    written = (tmp_path / "dossiers" / "p.md").read_text(encoding="utf-8")
    assert "пустой ответ" in written


def test_instructions_for_returns_only_advice(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path))
    learn(records=[rec(outcome="empty") for _ in range(3)])
    text = instructions_for("p")
    assert "prompt_file" in text
    assert "пустой ответ" not in text  # наблюдения в промпт не идут


def test_instructions_for_unknown_provider_is_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path))
    assert instructions_for("никого") == ""


def test_learn_advances_watermark_and_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path))
    for _ in range(3):
        append(rec(outcome="empty"))
    assert learn() == ["p"]
    assert learn() == []  # второй раз нечего дистиллировать


def test_should_auto_learn_threshold(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path))
    for _ in range(19):
        append(rec(outcome="crash"))
    assert should_auto_learn() is False
    append(rec(outcome="crash"))
    assert should_auto_learn() is True


def test_real_ben_voice_failure_yields_interpreter_advice():
    """Настоящий stderr от падения обёртки со своим venv обязан дать совет про интерпретатор."""
    real = (
        "Traceback (most recent call last):\n"
        '  File "/opt/tools/tts-wrapper.py", line 311, in <module>\n'
        "ModuleNotFoundError: No module named 'mlx_audio'"
    )
    rules = load_rules(Path(__file__).resolve().parents[1])
    lessons = distill([rec(provider="tts-wrapper", stderr=real) for _ in range(3)], rules)
    advice = [lesson.instruction for lesson in lessons if lesson.instruction]
    assert any("интерпретатор" in text for text in advice)


def test_real_ffmpeg_container_failure_yields_out_ext_advice():
    """И второй сегодняшний случай: ffmpeg не смог записать контейнер → совет про out_ext."""
    real = "[out#0/wav] Nothing was written into output file, because at least one stream"
    rules = load_rules(Path(__file__).resolve().parents[1])
    lessons = distill([rec(provider="tts-wrapper", stderr=real) for _ in range(3)], rules)
    advice = [lesson.instruction for lesson in lessons if lesson.instruction]
    assert any("out_ext" in text for text in advice)


def test_pending_count_tracks_unprocessed(monkeypatch, tmp_path):
    from nn.dossier import pending_count

    monkeypatch.setenv("NN_STATE", str(tmp_path))
    assert pending_count() == 0
    append(rec(outcome="crash"))
    append(rec(outcome="crash"))
    assert pending_count() == 2
    learn()
    assert pending_count() == 0


def test_load_rules_reads_repo_file():
    rules = load_rules(Path(__file__).resolve().parents[1])
    assert rules
    assert any("no module named" in needle for needle, _ in rules)

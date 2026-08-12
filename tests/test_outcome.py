from nn.outcome import classify


def base(**kw):
    args = dict(
        exit_code=0,
        out_path=None,
        out_type="text",
        stderr="",
        timed_out=False,
        quota_patterns=(),
    )
    args.update(kw)
    return classify(**args)


def test_timeout_wins_over_exit_code():
    assert base(timed_out=True, exit_code=124) == "timeout"


def test_quota_pattern_detected_in_stderr():
    got = base(exit_code=1, stderr="Error: usage limit reached", quota_patterns=("usage limit",))
    assert got == "quota"


def test_refusal_detected():
    assert base(exit_code=0, stderr="I can't help with that") == "refused"


def test_nonzero_exit_is_crash():
    assert base(exit_code=2, stderr="boom") == "crash"


def test_missing_output_file_is_empty(tmp_path):
    assert base(out_path=str(tmp_path / "nope.txt"), out_type="text") == "empty"


def test_zero_byte_output_is_empty(tmp_path):
    path = tmp_path / "a.wav"
    path.write_bytes(b"")
    assert base(out_path=str(path), out_type="audio") == "empty"


def test_short_text_output_is_empty(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("Ready to work.", encoding="utf-8")
    assert base(out_path=str(path), out_type="text") == "empty"


def test_long_enough_text_output_is_success(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("а" * 24, encoding="utf-8")
    assert base(out_path=str(path), out_type="text") == "success"


def test_binary_output_only_needs_nonzero_size(tmp_path):
    path = tmp_path / "a.wav"
    path.write_bytes(b"\x00\x01")
    assert base(out_path=str(path), out_type="audio") == "success"


def test_success_without_declared_output():
    assert base() == "success"


def test_quota_beats_crash_when_both_signals_present():
    got = base(exit_code=1, stderr="429 rate limit", quota_patterns=("rate limit",))
    assert got == "quota"

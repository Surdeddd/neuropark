import json
from datetime import UTC, datetime

from nn.catalog import Catalog
from nn.errors import Exit
from nn.model import Bridge, Capability, Host, Provider
from nn.resolve import Choice
from nn.run import execute, exit_code_for

NOW = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
LOCAL = Host(id="local", kind="local")
MANUAL_HOST = Host(id="gpu-box", kind="ssh", addr="gpu-box", auto=False)
CAPS = {"transcribe": Capability("transcribe", ("audio",), "srt")}
TYPES = {"audio": ("wav", "ogg"), "srt": ("srt",), "text": ("txt",)}

LONG_SRT = "1\\n00:00:00,000 --> 00:00:02,000\\nпривет мир достаточно длинный текст\\n"


def catalog() -> Catalog:
    return Catalog(
        providers={},
        hosts={"local": LOCAL},
        capabilities=CAPS,
        types=TYPES,
        bridges={},
        recipes={},
    )


def prov(**kw) -> Provider:
    defaults = dict(
        id="fake",
        capability="transcribe",
        kind="model",
        detect={"bin": "echo"},
        io_in=("audio",),
        io_out="srt",
        notes="n",
        source="providers/fake.json",
        run={"": f"printf '{LONG_SRT}' > {{out}}"},
    )
    defaults.update(kw)
    return Provider(**defaults)


def choice(provider: Provider, host: Host = LOCAL, bridge: Bridge | None = None) -> Choice:
    return Choice(
        provider=provider,
        host=host,
        bridge=bridge,
        manual=(host.kind == "manual" or not host.auto),
        in_type="audio",
        out_type="srt",
        rejected=(),
    )


def test_successful_run_writes_output_and_envelope(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    env = execute(
        choice(prov()), catalog=catalog(), in_path="a.wav", work_dir=str(tmp_path), now=NOW
    )
    assert env.outcome == "success"
    assert env.status == "ok"
    assert env.out is not None
    assert env.out.endswith(".srt")
    assert json.loads(env.to_json())["provider"] == "fake"
    assert exit_code_for(env) == Exit.OK


def test_out_ext_override_decides_file_extension(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    provider = prov(
        capability="tts",
        io_in=("text",),
        io_out="audio",
        out_ext="ogg",
        run={"": "printf opus-payload-long-enough-for-threshold > {out}"},
    )
    ch = Choice(
        provider=provider,
        host=LOCAL,
        bridge=None,
        manual=False,
        in_type="text",
        out_type="audio",
        rejected=(),
    )
    env = execute(ch, catalog=catalog(), in_path="a.txt", work_dir=str(tmp_path), now=NOW)
    assert env.out is not None
    assert env.out.endswith(".ogg")
    assert env.outcome == "success"


def test_pre_step_runs_before_run(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    provider = prov(
        pre={"": "printf converted-audio-payload-long-enough > {tmp}.wav"},
        run={"": "cp {tmp}.wav {out}"},
        io_out="audio",
    )
    env = execute(
        choice(provider), catalog=catalog(), in_path="a.wav", work_dir=str(tmp_path), now=NOW
    )
    assert env.outcome == "success"
    assert env.out is not None


def test_failing_provider_gives_crash_and_exit_four(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    env = execute(
        choice(prov(run={"": "echo boom >&2; exit 1"})),
        catalog=catalog(),
        in_path="a.wav",
        work_dir=str(tmp_path),
        now=NOW,
        retries=0,
    )
    assert env.outcome == "crash"
    assert exit_code_for(env) == Exit.PROVIDER_FAILED
    log = (tmp_path / "state" / "out" / f"{env.run_id}.log").read_text(encoding="utf-8")
    assert "boom" in log


def test_manual_host_prints_command_and_exits_three(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    env = execute(
        choice(prov(host="gpu-box"), host=MANUAL_HOST),
        catalog=catalog(),
        in_path="a.wav",
        work_dir=str(tmp_path),
        now=NOW,
    )
    assert env.status == "manual"
    assert env.command is not None
    assert "ssh gpu-box" in env.command
    assert exit_code_for(env) == Exit.MANUAL


def test_quota_outcome_is_not_retried(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    counter = tmp_path / "calls.txt"
    provider = prov(
        run={"": f"printf x >> {counter}; echo 'usage limit reached' >&2; exit 1"},
        quota_patterns=("usage limit",),
    )
    env = execute(
        choice(provider),
        catalog=catalog(),
        in_path="a.wav",
        work_dir=str(tmp_path),
        now=NOW,
        retries=2,
    )
    assert env.outcome == "quota"
    assert counter.read_text(encoding="utf-8") == "x"


def test_crash_is_retried_once(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    counter = tmp_path / "calls.txt"
    provider = prov(run={"": f"printf x >> {counter}; exit 1"})
    execute(
        choice(provider),
        catalog=catalog(),
        in_path="a.wav",
        work_dir=str(tmp_path),
        now=NOW,
        retries=1,
    )
    assert counter.read_text(encoding="utf-8") == "xx"


def test_bridge_runs_before_provider(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    bridge = Bridge(
        id="text-to-audio-fake",
        frm="text",
        to="audio",
        detect={"bin": "echo"},
        run={"": "printf audio-payload-long-enough-for-threshold > {out}"},
        out_ext="wav",
    )
    provider = prov(run={"": "cp {in} {out}"}, io_out="audio")
    env = execute(
        choice(provider, bridge=bridge),
        catalog=catalog(),
        in_path="note.txt",
        work_dir=str(tmp_path),
        now=NOW,
    )
    assert env.bridge == "text-to-audio-fake"
    assert env.outcome == "success"


def test_failing_bridge_stops_before_provider(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    bridge = Bridge(
        id="broken-bridge",
        frm="text",
        to="audio",
        detect={"bin": "echo"},
        run={"": "exit 9"},
        out_ext="wav",
    )
    env = execute(
        choice(prov(), bridge=bridge),
        catalog=catalog(),
        in_path="note.txt",
        work_dir=str(tmp_path),
        now=NOW,
    )
    assert env.outcome == "crash"
    assert env.bridge == "broken-bridge"


def test_run_appends_to_runlog(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    execute(choice(prov()), catalog=catalog(), in_path="a.wav", work_dir=str(tmp_path), now=NOW)
    lines = (tmp_path / "state" / "runs.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["capability"] == "transcribe"


def test_envelope_json_uses_in_key_not_in_path(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    env = execute(
        choice(prov()), catalog=catalog(), in_path="a.wav", work_dir=str(tmp_path), now=NOW
    )
    payload = json.loads(env.to_json())
    assert payload["in"] == "a.wav"
    assert "in_path" not in payload


def test_manual_run_is_not_written_to_runlog(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    execute(
        choice(prov(host="gpu-box"), host=MANUAL_HOST),
        catalog=catalog(),
        in_path="a.wav",
        work_dir=str(tmp_path),
        now=NOW,
    )
    assert not (tmp_path / "state" / "runs.jsonl").exists()


def test_unknown_template_variable_is_reported(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    import pytest

    from nn.errors import NnError

    with pytest.raises(NnError) as err:
        execute(
            choice(prov(run={"": "tool {mystery}"})),
            catalog=catalog(),
            in_path="a.wav",
            work_dir=str(tmp_path),
            now=NOW,
        )
    assert err.value.code == Exit.BAD_DATA
    assert "mystery" in err.value.message


def test_run_ids_differ_within_one_second():
    """Два прогона в одну секунду получали один run_id и затирали друг друга.

    Проверено живьём: два параллельных whisper вернули один и тот же `out`.
    """
    from datetime import UTC, datetime

    from nn.run import new_run_id

    moment = datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC)
    ids = {new_run_id("whisper-cpp", moment) for _ in range(1000)}
    assert len(ids) == 1000, "внутри процесса уникальность обязана быть гарантированной"
    assert all(one.startswith(f"{int(moment.timestamp())}-") for one in ids)
    assert all(one.endswith("-whisper-cpp") for one in ids)


def test_run_id_keeps_the_second_first_so_files_sort_by_time():
    from datetime import UTC, datetime

    from nn.run import new_run_id

    early = new_run_id("p", datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC))
    later = new_run_id("p", datetime(2026, 8, 13, 12, 0, 1, tzinfo=UTC))
    assert sorted([later, early]) == [early, later]

"""Транспорт ssh: раскладка путей, скрипт для той стороны, охрана уборки.

Живой прогон против настоящего sshd — в test_smoke_ssh.py.
"""

from pathlib import Path

import pytest

from nn.model import Host
from nn.transport.base import Executed
from nn.transport.ssh import (
    SshTransport,
    build_script,
    is_safe_remote_dir,
    remote_dir_for,
)

HOST = Host(id="box", kind="ssh", addr="box", auto=True)


class Recorder(SshTransport):
    """Тот же транспорт, но вместо ssh записывает вызовы: сети в юнитах нет."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.calls: list[tuple[list[str], str | None]] = []
        self.transfers: list[tuple[list[str], str | None, str | None]] = []
        self.listing = ""
        self.produced: dict[str, str] = {}

    def _run(self, argv, *, timeout_s, stdin=None):
        argv = list(argv)
        self.calls.append((argv, stdin))
        if "ls" in argv:
            return Executed(0, self.listing, "", False, " ".join(argv))
        return Executed(0, "", "", False, " ".join(argv))

    def _stream(self, argv, *, timeout_s, stdin_file=None, stdout_file=None):
        argv = list(argv)
        self.transfers.append(
            (
                argv,
                str(stdin_file) if stdin_file else None,
                str(stdout_file) if stdout_file else None,
            )
        )
        if stdout_file is not None:
            name = argv[-1].rsplit("/", 1)[-1]
            stdout_file.write_text(self.produced.get(name, "payload"), encoding="utf-8")
        return Executed(0, "", "", False, " ".join(argv))


def test_remote_dir_lives_under_host_tmp_when_declared():
    host = Host(id="box", kind="ssh", addr="box", paths={"tmp": "/data/scratch/"})
    assert remote_dir_for(host, "42-x") == "/data/scratch/nn-42-x"
    assert remote_dir_for(HOST, "42-x") == "/tmp/nn-42-x"


@pytest.mark.parametrize(
    ("path", "run_id", "safe"),
    [
        ("/tmp/nn-17-whisper", "17-whisper", True),
        ("/data/x/nn-17", "17", True),
        ("/tmp", "17", False),
        ("/", "17", False),
        ("/tmp/nn-", "", False),
        ("/tmp/../nn-17", "17", False),
        ("relative/nn-17", "17", False),
        ("/tmp/nn-17", "a/b", False),
    ],
)
def test_cleanup_guard_only_allows_our_own_directory(path, run_id, safe):
    """rm -rf на той стороне обязан быть невозможен нигде, кроме своей директории."""
    assert is_safe_remote_dir(path, run_id) is safe


def test_cleanup_is_skipped_when_the_guard_says_no():
    transport = Recorder()
    transport.addr = "box"
    transport.remote_dir = "/tmp"
    transport.run_id = "17"
    transport.finish()
    assert not any("rm" in argv for argv, _ in transport.calls)


def test_cleanup_runs_for_our_own_directory():
    transport = Recorder()
    transport.addr = "box"
    transport.remote_dir = "/tmp/nn-17"
    transport.run_id = "17"
    transport.finish()
    removals = [argv for argv, _ in transport.calls if "rm" in argv]
    assert removals
    assert removals[0][-1] == "/tmp/nn-17"


def test_prepare_moves_only_local_file_paths(tmp_path):
    source = tmp_path / "talk.wav"
    source.write_bytes(b"\x00")
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("hi", encoding="utf-8")
    context = {
        "in": str(source),
        "out": str(tmp_path / "out" / "result.srt"),
        "out_base": str(tmp_path / "out" / "result"),
        "tmp": str(tmp_path / "run-tmp"),
        "dir": str(tmp_path),
        "prompt_file": str(prompt),
        "model": "/opt/models/ggml-large.bin",
        "host.paths.models": "/data/models",
    }
    transport = Recorder()
    prepared = transport.prepare(context, host=HOST, run_id="17", env={})

    assert prepared.failure is None
    remote = prepared.context
    assert remote["in"] == "/tmp/nn-17/talk.wav"
    assert remote["prompt_file"] == "/tmp/nn-17/prompt.txt"
    assert remote["out"] == "/tmp/nn-17/result.srt"
    assert remote["out_base"] == "/tmp/nn-17/result"
    assert remote["tmp"] == "/tmp/nn-17/run-tmp"
    assert remote["dir"] == "/tmp/nn-17"
    # Пути той стороны остаются как есть: подмена сломала бы их.
    assert remote["model"] == "/opt/models/ggml-large.bin"
    assert remote["host.paths.models"] == "/data/models"


def test_prepare_uploads_every_existing_input(tmp_path):
    source = tmp_path / "a.wav"
    source.write_bytes(b"\x00")
    subs = tmp_path / "subs.srt"
    subs.write_text("1\n", encoding="utf-8")
    context = {"in": str(source), "extra0": str(subs), "out": str(tmp_path / "o.mp4")}
    transport = Recorder()
    transport.prepare(context, host=HOST, run_id="17", env={})

    sent = {local for _, local, _ in transport.transfers}
    assert sent == {str(source), str(subs)}, "оба входа обязаны улететь на ту сторону"
    targets = [argv[-1] for argv, _, _ in transport.transfers]
    assert "cat > /tmp/nn-17/a.wav" in targets
    assert "cat > /tmp/nn-17/subs.srt" in targets


def test_prepare_ignores_an_input_that_does_not_exist(tmp_path):
    """Провайдеры без входа (text по промпту) не должны ронять подготовку."""
    context = {"in": str(tmp_path / "absent.wav"), "out": str(tmp_path / "o.txt")}
    transport = Recorder()
    prepared = transport.prepare(context, host=HOST, run_id="17", env={})
    assert prepared.failure is None
    assert transport.transfers == []


def test_prepare_reports_a_dead_host_as_a_failure_not_an_exception(tmp_path):
    class Dead(SshTransport):
        def _run(self, argv, *, timeout_s, stdin=None):
            return Executed(
                255, "", "ssh: connect to host box port 22: Connection refused", False, "ssh"
            )

        def _stream(self, argv, *, timeout_s, stdin_file=None, stdout_file=None):
            return Executed(
                255, "", "ssh: connect to host box port 22: Connection refused", False, "ssh"
            )

    prepared = Dead().prepare({"out": str(tmp_path / "o.txt")}, host=HOST, run_id="17", env={})
    assert prepared.failure is not None
    assert prepared.failure.exit_code == 255
    assert "Connection refused" in prepared.failure.stderr


def test_host_without_addr_is_a_data_error():
    from nn.errors import NnError

    with pytest.raises(NnError):
        SshTransport().prepare({}, host=Host(id="box", kind="ssh"), run_id="17", env={})


def test_script_carries_env_and_cd_before_the_command():
    script = build_script("whisper -m model", remote_dir="/tmp/nn-17", env={"KEY": "s3cret"})
    lines = script.splitlines()
    assert lines[0] == "cd /tmp/nn-17 || exit 1"
    assert lines[1] == "export KEY=s3cret"
    assert lines[-1] == "whisper -m model"


def test_script_quotes_values_that_need_it():
    """Токен с пробелом или кавычкой не должен разваливать скрипт на той стороне."""
    script = build_script(
        "run", remote_dir="/tmp/nn 17", env={"KEY": "a b'c", "PATH": "/opt/homebrew/bin:/usr/bin"}
    )
    assert "cd '/tmp/nn 17' || exit 1" in script
    assert "export KEY='a b'\"'\"'c'" in script
    assert "export PATH=/opt/homebrew/bin:/usr/bin" in script


def test_execute_sends_the_script_on_stdin_and_keeps_the_provider_command():
    transport = Recorder()
    transport.addr = "box"
    transport.remote_dir = "/tmp/nn-17"
    transport.run_id = "17"
    result = transport.execute(
        "whisper -m /m.bin", host=HOST, timeout_s=60, work_dir="/local", env={"K": "v"}
    )
    argv, stdin = transport.calls[-1]
    assert argv[:1] == ["ssh"]
    assert argv[-2:] == ["sh", "-s"]
    assert stdin is not None
    assert "export K=v" in stdin
    # Секрет не должен попасть в argv: там его видно в ps на удалённой машине.
    assert not any(part == "v" for part in argv)
    assert not any("whisper" in part for part in argv)
    assert result.command == "whisper -m /m.bin"


def test_collect_brings_back_the_output_and_its_siblings(tmp_path):
    """Провайдер мог писать {out_base}.srt — забрать нужно и это."""
    local_out = tmp_path / "result.srt"
    transport = Recorder()
    transport.addr = "box"
    transport.remote_dir = "/tmp/nn-17"
    transport.run_id = "17"
    transport.downloads = [("/tmp/nn-17/result.srt", str(local_out))]
    transport.listing = "talk.wav\nresult.srt\nresult.txt\n"
    transport.produced = {"result.srt": "subs", "result.txt": "plain"}
    assert transport.collect() is None
    pulled = [argv[-1] for argv, _, _ in transport.transfers]
    assert "/tmp/nn-17/result.srt" in pulled
    assert "/tmp/nn-17/result.txt" in pulled
    assert "/tmp/nn-17/talk.wav" not in pulled
    assert local_out.read_text(encoding="utf-8") == "subs"
    assert (local_out.parent / "result.txt").read_text(encoding="utf-8") == "plain"


def test_collect_is_quiet_when_the_remote_produced_nothing(tmp_path):
    transport = Recorder()
    transport.addr = "box"
    transport.remote_dir = "/tmp/nn-17"
    transport.run_id = "17"
    transport.downloads = [("/tmp/nn-17/result.srt", str(tmp_path / "result.srt"))]
    transport.listing = "talk.wav\n"
    assert transport.collect() is None
    assert transport.transfers == []


def test_collect_reports_a_broken_transfer(tmp_path):
    class Broken(Recorder):
        def _stream(self, argv, *, timeout_s, stdin_file=None, stdout_file=None):
            super()._stream(
                argv, timeout_s=timeout_s, stdin_file=stdin_file, stdout_file=stdout_file
            )
            return Executed(1, "", "ssh: connection closed by remote host", False, "ssh")

    transport = Broken()
    transport.addr = "box"
    transport.remote_dir = "/tmp/nn-17"
    transport.run_id = "17"
    transport.downloads = [("/tmp/nn-17/o.srt", str(tmp_path / "o.srt"))]
    transport.listing = "o.srt\n"
    failure = transport.collect()
    assert failure is not None
    assert "connection closed" in failure.stderr


def test_batch_mode_is_always_on():
    """Без BatchMode ssh может зависнуть на приглашении пароля и съесть таймаут."""
    transport = Recorder()
    transport.addr = "box"
    transport.remote_dir = "/tmp/nn-17"
    transport.run_id = "17"
    transport.execute("true", host=HOST, timeout_s=5, work_dir="/x", env={})
    argv, _ = transport.calls[-1]
    assert "BatchMode=yes" in argv


def test_local_and_manual_transports_satisfy_the_same_protocol():
    from nn.transport import LocalTransport, ManualTransport

    for transport in (LocalTransport(), ManualTransport()):
        prepared = transport.prepare({"in": "x"}, host=HOST, run_id="17", env={})
        assert prepared.context == {"in": "x"}
        assert prepared.failure is None
        assert transport.collect() is None
        assert transport.finish() is None


def test_get_transport_returns_ssh_for_an_auto_ssh_host():
    from nn.transport import SshTransport as Exported
    from nn.transport import get_transport

    assert isinstance(get_transport(HOST), Exported)
    manual = Host(id="box", kind="ssh", addr="box", auto=False)
    assert not isinstance(get_transport(manual), Exported)


def test_unreachable_host_at_scan_time_is_stale_not_missing(tmp_path, monkeypatch):
    """Хост не ответил — статус stale и честная причина, а не «бинаря нет».

    Настоящий ssh на порт 1: соединение отвергается мгновенно, сети не нужно.
    Про инструмент мы в этом случае не узнали ничего, и говорить «его нет» — врать.
    """
    import json

    from nn.cli import main
    from nn.errors import Exit

    data = tmp_path / "data"
    (data / "providers").mkdir(parents=True)
    (data / "hosts").mkdir(parents=True)
    (data / "providers" / "remote-text.json").write_text(
        json.dumps(
            {
                "id": "remote-text",
                "capability": "text",
                "kind": "agent",
                "host": "deadbox",
                "detect": {"bin": "sh"},
                "io": {"in": ["text"], "out": "text"},
                "run": "cat {prompt_file} > {out}",
                "notes": {"en": "remote", "ru": "удалённый"},
            }
        ),
        encoding="utf-8",
    )
    (data / "hosts" / "deadbox.json").write_text(
        json.dumps(
            {
                "id": "deadbox",
                "kind": "ssh",
                "addr": "127.0.0.1",
                "auto": True,
                "paths": {"tmp": "/tmp"},
                "ssh_options": ["-p", "1"],
            }
        ),
        encoding="utf-8",
    )
    (data / "hosts" / "local.json").write_text(
        json.dumps({"id": "local", "kind": "local"}), encoding="utf-8"
    )
    (data / "capabilities.json").write_text(
        json.dumps(
            {"types": {"text": ["txt"]}, "capabilities": {"text": {"in": ["text"], "out": "text"}}}
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NN_DATA", str(data))
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))

    assert main(["scan"]) == int(Exit.OK)
    registry = json.loads(
        next((tmp_path / "state").glob("registry.*.json")).read_text(encoding="utf-8")
    )
    entry = registry["entries"]["remote-text"]
    assert entry["status"] == "stale", entry
    assert "не ответил" in entry["reason"] or "did not answer" in entry["reason"], entry
    assert "sh" not in entry["reason"].split(), "про бинарь мы ничего не узнали"

    # Резолвер такого провайдера не берёт: он отказывается ДО запуска.
    assert main(["run", "text", "--prompt", "hi", "--provider", "remote-text"]) == int(
        Exit.NO_PROVIDER
    )
    assert not (tmp_path / "state" / "runs.jsonl").exists(), "ничего не запускалось — журнал пуст"


def test_host_that_dies_after_the_scan_becomes_a_recorded_run(tmp_path, monkeypatch):
    """Хост был жив на скане и умер к запуску — это исход в журнале, а не исключение.

    Именно так досье учатся на «connection refused»: реестр говорит ok, а прогон
    падает на подготовке.
    """
    import json as jsonlib

    from nn.cli import main
    from nn.errors import Exit
    from nn.registry import Entry, Registry, hostname, save

    data = tmp_path / "data"
    (data / "providers").mkdir(parents=True)
    (data / "hosts").mkdir(parents=True)
    (data / "providers" / "remote-text.json").write_text(
        jsonlib.dumps(
            {
                "id": "remote-text",
                "capability": "text",
                "kind": "agent",
                "host": "deadbox",
                "detect": {"bin": "sh"},
                "io": {"in": ["text"], "out": "text"},
                "run": "cat {prompt_file} > {out}",
                "notes": {"en": "remote", "ru": "удалённый"},
            }
        ),
        encoding="utf-8",
    )
    (data / "hosts" / "deadbox.json").write_text(
        jsonlib.dumps(
            {
                "id": "deadbox",
                "kind": "ssh",
                "addr": "127.0.0.1",
                "auto": True,
                "paths": {"tmp": "/tmp"},
                "ssh_options": ["-p", "1"],
            }
        ),
        encoding="utf-8",
    )
    (data / "hosts" / "local.json").write_text(
        jsonlib.dumps({"id": "local", "kind": "local"}), encoding="utf-8"
    )
    (data / "capabilities.json").write_text(
        jsonlib.dumps(
            {"types": {"text": ["txt"]}, "capabilities": {"text": {"in": ["text"], "out": "text"}}}
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NN_DATA", str(data))
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))

    # Реестр от того момента, когда хост ещё отвечал.
    save(
        Registry(
            hostname=hostname(),
            generated_at="2026-08-13T00:00:00+00:00",
            entries={"remote-text": Entry("remote-text", "deadbox", "ok", "", None, "2026-08-13")},
        )
    )

    assert main(["run", "text", "--prompt", "hi", "--provider", "remote-text"]) == int(
        Exit.PROVIDER_FAILED
    )
    runs = (tmp_path / "state" / "runs.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert runs, "прогон обязан попасть в журнал"
    record = jsonlib.loads(runs[-1])
    assert record["provider"] == "remote-text"
    assert record["host"] == "deadbox"
    assert record["outcome"] == "crash"
    assert record["stderr_tail"]


def test_host_ssh_options_reach_the_command_line():
    from nn.transport import get_transport

    host = Host(id="box", kind="ssh", addr="box", ssh_options=("-p", "2222"))
    transport = get_transport(host)
    assert transport.ssh_options == ("-p", "2222")


def test_no_hardcoded_out_dir_assumption(tmp_path):
    """Выход может лежать где угодно: забираем в ту же папку, куда просили."""
    nested = tmp_path / "deep" / "deeper"
    context = {"out": str(nested / "r.srt")}
    transport = Recorder()
    prepared = transport.prepare(context, host=HOST, run_id="17", env={})
    assert prepared.context["out"] == "/tmp/nn-17/r.srt"
    assert transport.downloads == [("/tmp/nn-17/r.srt", str(nested / "r.srt"))]
    assert not Path(nested).exists()  # директория создаётся только при выкачке


def test_failed_preparation_still_cleans_up_the_remote_directory(tmp_path, monkeypatch):
    """Заливка упала после mkdir — директория не должна остаться на той стороне.

    Поймано живым прогоном: после неудачной подготовки на удалённой машине копились
    директории прогонов, и удалить их было некому.
    """
    import json

    from nn.cli import main
    from nn.errors import Exit

    data = tmp_path / "data"
    (data / "providers").mkdir(parents=True)
    (data / "hosts").mkdir(parents=True)
    (data / "providers" / "remote-text.json").write_text(
        json.dumps(
            {
                "id": "remote-text",
                "capability": "text",
                "kind": "agent",
                "host": "halfbox",
                "detect": {"bin": "sh"},
                "io": {"in": ["text"], "out": "text"},
                "run": "cat {prompt_file} > {out}",
                "notes": {"en": "remote", "ru": "удалённый"},
            }
        ),
        encoding="utf-8",
    )
    (data / "hosts" / "halfbox.json").write_text(
        json.dumps({"id": "halfbox", "kind": "ssh", "addr": "box", "auto": True}),
        encoding="utf-8",
    )
    (data / "hosts" / "local.json").write_text(
        json.dumps({"id": "local", "kind": "local"}), encoding="utf-8"
    )
    (data / "capabilities.json").write_text(
        json.dumps(
            {"types": {"text": ["txt"]}, "capabilities": {"text": {"in": ["text"], "out": "text"}}}
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NN_DATA", str(data))
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))

    seen: list[list[str]] = []

    class HalfBroken(SshTransport):
        """mkdir проходит, заливка падает — самый неприятный из отказов."""

        def _run(self, argv, *, timeout_s, stdin=None):
            seen.append(list(argv))
            return Executed(0, "", "", False, " ".join(argv))

        def _stream(self, argv, *, timeout_s, stdin_file=None, stdout_file=None):
            seen.append(list(argv))
            return Executed(1, "", "ssh: broken pipe", False, " ".join(argv))

    monkeypatch.setattr("nn.transport.SshTransport", HalfBroken)
    # Детект теперь идёт на ту сторону, поэтому реестр пишем как от живого хоста:
    # проверяем именно уборку после провала заливки, а не поведение скана.
    from nn.registry import Entry, Registry, hostname, save

    save(
        Registry(
            hostname=hostname(),
            generated_at="2026-08-13T00:00:00+00:00",
            entries={"remote-text": Entry("remote-text", "halfbox", "ok", "", None, "2026-08-13")},
        )
    )

    assert main(["run", "text", "--prompt", "hi", "--provider", "remote-text"]) == int(
        Exit.PROVIDER_FAILED
    )
    assert any("rm" in argv for argv in seen), "уборка обязана произойти и после провала"

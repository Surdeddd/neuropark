"""Живой ssh: настоящий sshd, настоящая переброска файлов, настоящая уборка.

Нужен доступный по ключу хост:

    NN_SSH_SMOKE_HOST   адрес (не задан → тесты пропускаются, а не притворяются)
    NN_SSH_SMOKE_OPTS   опции ssh/scp через пробел (порт, ключ, known_hosts)

Локально это поднимается изолированным sshd на высоком порту: свой host key, свой
authorized_keys во временной директории, конфиг пользователя не тронут. Как именно —
в MEMORY_BANK/design/ssh-transport.md.
"""

import json
import os
import shlex
import shutil
import subprocess

import pytest

from nn.cli import main
from nn.errors import Exit
from nn.model import Host
from nn.render import render
from nn.transport.ssh import SshTransport

HOST_ADDR = os.environ.get("NN_SSH_SMOKE_HOST", "")
OPTS = tuple(shlex.split(os.environ.get("NN_SSH_SMOKE_OPTS", "")))

pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(not HOST_ADDR, reason="NN_SSH_SMOKE_HOST не задан"),
]

CAPS = {"types": {"text": ["txt"]}, "capabilities": {"text": {"in": ["text"], "out": "text"}}}


def host() -> Host:
    return Host(
        id="smoke",
        kind="ssh",
        addr=HOST_ADDR,
        auto=True,
        paths={"tmp": "/tmp"},
        ssh_options=OPTS,
    )


def transport() -> SshTransport:
    return SshTransport(ssh_options=OPTS)


def remote(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", *OPTS, HOST_ADDR, *argv],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_round_trip_moves_input_there_and_output_back(tmp_path):
    """Файл уезжает, команда работает над ним на той стороне, результат возвращается."""
    source = tmp_path / "input.txt"
    source.write_text("строка один\nstring two\n", encoding="utf-8")
    out = tmp_path / "result.txt"

    ssh = transport()
    prepared = ssh.prepare(
        {"in": str(source), "out": str(out), "dir": str(tmp_path)},
        host=host(),
        run_id="smoke-roundtrip",
        env={},
    )
    assert prepared.failure is None, prepared.failure
    assert prepared.context["in"] == "/tmp/nn-smoke-roundtrip/input.txt"

    result = ssh.execute(
        f"wc -l < {shlex.quote(prepared.context['in'])} > {shlex.quote(prepared.context['out'])}",
        host=host(),
        timeout_s=60,
        work_dir=str(tmp_path),
        env={},
    )
    assert result.exit_code == 0, result.stderr

    assert ssh.collect() is None
    assert out.is_file(), "выход обязан вернуться на эту машину"
    assert out.read_text(encoding="utf-8").strip() == "2"

    ssh.finish()
    assert remote("ls", "/tmp/nn-smoke-roundtrip").returncode != 0, "директория не убрана"


def test_env_reaches_the_command(tmp_path):
    out = tmp_path / "env.txt"
    ssh = transport()
    prepared = ssh.prepare(
        {"out": str(out)}, host=host(), run_id="smoke-env", env={"NN_SECRET": "topolino"}
    )
    assert prepared.failure is None, prepared.failure
    result = ssh.execute(
        f'printf %s "$NN_SECRET" > {shlex.quote(prepared.context["out"])}',
        host=host(),
        timeout_s=60,
        work_dir=str(tmp_path),
        env={"NN_SECRET": "topolino"},
    )
    assert result.exit_code == 0, result.stderr
    assert ssh.collect() is None
    assert out.read_text(encoding="utf-8") == "topolino"
    assert result.command.startswith("printf"), "в конверте команда провайдера, а не обёртка"
    ssh.finish()


def test_secret_never_lands_on_the_remote_disk(tmp_path):
    """Секрет живёт в памяти шелла: ни в файлах рабочей директории, ни в argv."""
    ssh = transport()
    prepared = ssh.prepare(
        {"out": str(tmp_path / "o.txt")},
        host=host(),
        run_id="smoke-nosecret",
        env={"NN_SECRET": "topolino"},
    )
    assert prepared.failure is None, prepared.failure
    ssh.execute(
        "grep -rl topolino . > found.txt 2>/dev/null; true",
        host=host(),
        timeout_s=60,
        work_dir=str(tmp_path),
        env={"NN_SECRET": "topolino"},
    )
    found = remote("cat", "/tmp/nn-smoke-nosecret/found.txt")
    assert found.stdout.strip() == "", found.stdout
    ssh.finish()


def test_sibling_output_comes_back_too(tmp_path):
    """Провайдеры вроде whisper пишут {out_base}.ext — это тоже надо забрать."""
    out = tmp_path / "take.srt"
    ssh = transport()
    prepared = ssh.prepare({"out": str(out)}, host=host(), run_id="smoke-sibling", env={})
    assert prepared.failure is None, prepared.failure
    base = prepared.context["out_base"]
    result = ssh.execute(
        f"printf sub > {shlex.quote(base + '.srt')}; printf txt > {shlex.quote(base + '.txt')}",
        host=host(),
        timeout_s=60,
        work_dir=str(tmp_path),
        env={},
    )
    assert result.exit_code == 0, result.stderr
    assert ssh.collect() is None
    assert out.read_text(encoding="utf-8") == "sub"
    assert (tmp_path / "take.txt").read_text(encoding="utf-8") == "txt"
    ssh.finish()


def test_a_missing_tool_on_the_far_side_is_reported_with_its_stderr(tmp_path):
    ssh = transport()
    prepared = ssh.prepare({"out": str(tmp_path / "x")}, host=host(), run_id="smoke-fail", env={})
    assert prepared.failure is None, prepared.failure
    result = ssh.execute(
        "definitely-not-installed-xyz", host=host(), timeout_s=30, work_dir=str(tmp_path), env={}
    )
    assert result.exit_code != 0
    assert "not found" in result.stderr.lower()
    ssh.finish()


def _write_remote_catalog(data, *, addr, options):
    (data / "providers").mkdir(parents=True)
    (data / "hosts").mkdir(parents=True)
    (data / "providers" / "remote-echo.json").write_text(
        json.dumps(
            {
                "id": "remote-echo",
                "capability": "text",
                "kind": "agent",
                "host": "smokebox",
                "detect": {"bin": "sh"},
                "io": {"in": ["text"], "out": "text"},
                "run": "tr a-z A-Z < {prompt_file} > {out}",
                "notes": {"en": "uppercase on the far side", "ru": "апперкейс на той стороне"},
            }
        ),
        encoding="utf-8",
    )
    (data / "hosts" / "smokebox.json").write_text(
        json.dumps(
            {
                "id": "smokebox",
                "kind": "ssh",
                "addr": addr,
                "auto": True,
                "paths": {"tmp": "/tmp"},
                "ssh_options": list(options),
            }
        ),
        encoding="utf-8",
    )
    (data / "hosts" / "local.json").write_text(
        json.dumps({"id": "local", "kind": "local"}), encoding="utf-8"
    )
    (data / "capabilities.json").write_text(json.dumps(CAPS), encoding="utf-8")


def test_full_cli_run_lands_the_output_and_leaves_nothing_behind(tmp_path, monkeypatch):
    """nn run целиком через CLI на живой хост: промпт туда, результат сюда, следов нет."""
    data = tmp_path / "data"
    _write_remote_catalog(data, addr=HOST_ADDR, options=OPTS)
    monkeypatch.setenv("NN_DATA", str(data))
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))

    assert main(["scan"]) == int(Exit.OK)
    # Текст длиннее порога пустого ответа (24 непробельных знака), иначе исход
    # честно классифицируется как empty и это будет не про транспорт.
    prompt = "hello remote machine, this line is long enough to count"
    assert main(["run", "text", "--prompt", prompt, "--provider", "remote-echo"]) == int(Exit.OK)

    bodies = [
        path.read_text(encoding="utf-8") for path in sorted((tmp_path / "state" / "out").glob("*"))
    ]
    assert any("HELLO REMOTE MACHINE" in body for body in bodies), bodies

    listing = remote("ls", "-1", "/tmp").stdout.splitlines()
    assert [name for name in listing if name.startswith("nn-") and "remote-echo" in name] == []


def test_detection_happens_on_the_far_side_with_the_host_env(tmp_path, monkeypatch):
    """Инструмент виден только удалённому шеллу — значит детект прошёл именно там.

    Бинарь лежит в каталоге, которого нет ни в моём PATH, ни в списке мест, куда
    смотрит локальный детект. Удалённая сторона находит его только потому, что
    каталог прописан в env хоста. Раньше детект всегда шёл локально и такой
    провайдер считался отсутствующим.
    """
    far = tmp_path / "far-bin"
    far.mkdir()
    tool = far / "nn-far-tool"
    tool.write_text("#!/bin/sh\nprintf far\n", encoding="utf-8")
    tool.chmod(0o755)
    assert shutil.which("nn-far-tool") is None, "локально его быть не должно"

    data = tmp_path / "data"
    (data / "providers").mkdir(parents=True)
    (data / "hosts").mkdir(parents=True)
    (data / "providers" / "far-tool.json").write_text(
        json.dumps(
            {
                "id": "far-tool",
                "capability": "text",
                "kind": "tool",
                "host": "smokebox",
                "detect": {"bin": "nn-far-tool"},
                "io": {"in": ["text"], "out": "text"},
                "run": "nn-far-tool > {out}",
                "notes": {"en": "only on the far side", "ru": "только на той стороне"},
            }
        ),
        encoding="utf-8",
    )
    (data / "hosts" / "smokebox.json").write_text(
        json.dumps(
            {
                "id": "smokebox",
                "kind": "ssh",
                "addr": HOST_ADDR,
                "auto": True,
                "paths": {"tmp": "/tmp"},
                "ssh_options": list(OPTS),
                "env": {"PATH": f"{far}:/usr/bin:/bin"},
            }
        ),
        encoding="utf-8",
    )
    (data / "hosts" / "local.json").write_text(
        json.dumps({"id": "local", "kind": "local"}), encoding="utf-8"
    )
    (data / "capabilities.json").write_text(json.dumps(CAPS), encoding="utf-8")
    monkeypatch.setenv("NN_DATA", str(data))
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))

    assert main(["scan"]) == int(Exit.OK)
    registry = json.loads(
        next((tmp_path / "state").glob("registry.*.json")).read_text(encoding="utf-8")
    )
    assert registry["entries"]["far-tool"]["status"] == "ok", registry["entries"]["far-tool"]


def test_a_tool_absent_on_the_far_side_is_not_saved_by_local_presence(tmp_path, monkeypatch):
    """Обратная сторона: инструмент есть в моём PATH, а в PATH удалённого шелла — нет.

    Инструмент создаётся тестом, а не берётся наугад из системы: раньше здесь
    предполагалось, что рядом есть `uv`, и на чистом раннере тест падал не по делу.
    """
    near = tmp_path / "near-bin"
    near.mkdir()
    tool = near / "nn-local-only"
    tool.write_text("#!/bin/sh\nprintf near\n", encoding="utf-8")
    tool.chmod(0o755)
    monkeypatch.setenv("PATH", f"{near}:{os.environ['PATH']}")
    assert shutil.which("nn-local-only") is not None, "локально он обязан находиться"

    data = tmp_path / "data"
    (data / "providers").mkdir(parents=True)
    (data / "hosts").mkdir(parents=True)
    (data / "providers" / "local-only.json").write_text(
        json.dumps(
            {
                "id": "local-only",
                "capability": "text",
                "kind": "tool",
                "host": "smokebox",
                "detect": {"bin": "nn-local-only"},
                "io": {"in": ["text"], "out": "text"},
                "run": "nn-local-only > {out}",
                "notes": {"en": "here but not there", "ru": "здесь есть, там нет"},
            }
        ),
        encoding="utf-8",
    )
    (data / "hosts" / "smokebox.json").write_text(
        json.dumps(
            {
                "id": "smokebox",
                "kind": "ssh",
                "addr": HOST_ADDR,
                "auto": True,
                "paths": {"tmp": "/tmp"},
                "ssh_options": list(OPTS),
                "env": {"PATH": "/usr/bin:/bin"},
            }
        ),
        encoding="utf-8",
    )
    (data / "hosts" / "local.json").write_text(
        json.dumps({"id": "local", "kind": "local"}), encoding="utf-8"
    )
    (data / "capabilities.json").write_text(json.dumps(CAPS), encoding="utf-8")
    monkeypatch.setenv("NN_DATA", str(data))
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))

    assert main(["scan"]) == int(Exit.OK)
    registry = json.loads(
        next((tmp_path / "state").glob("registry.*.json")).read_text(encoding="utf-8")
    )
    entry = registry["entries"]["local-only"]
    assert entry["status"] == "missing", entry
    assert "nn-local-only" in entry["reason"], entry


def test_batched_detect_names_the_real_reason_over_live_ssh():
    """Все проверки одним коннектом, и причина указывает на ту, что действительно упала."""
    from nn.detect import detect_over_runner
    from nn.transport.ssh import runner_for

    probe = runner_for(host(), {"PATH": "/usr/bin:/bin"})

    ok = detect_over_runner({"bin": "sh", "files": ["/etc/hosts"]}, env={}, runner=probe)
    assert ok.status == "ok", ok

    # Первая проверка проходит, вторая — нет: причина обязана быть про файл.
    partial = detect_over_runner(
        {"bin": "sh", "files": ["/definitely/not/here"]}, env={}, runner=probe
    )
    assert partial.status == "missing", partial
    assert "not/here" in partial.reason, partial.reason

    # Обратный порядок: падает первая.
    first = detect_over_runner(
        {"bin": "definitely-not-installed-xyz", "files": ["/etc/hosts"]}, env={}, runner=probe
    )
    assert first.status == "missing", first
    assert "definitely-not-installed-xyz" in first.reason, first.reason


def test_home_is_the_remote_home_not_ours():
    """`~/x` раскрывает шелл той стороны: домашняя директория там своя."""
    from nn.detect import detect_over_runner
    from nn.transport.ssh import runner_for

    probe = runner_for(host(), {})
    marker = ".nn-home-probe"
    # ssh склеивает argv пробелами, поэтому команда идёт одной строкой: иначе
    # `sh -c` заберёт только первое слово, а остальное станет $0.
    assert remote(f'touch "$HOME/{marker}"').returncode == 0
    try:
        found = detect_over_runner({"files": [f"~/{marker}"]}, env={}, runner=probe)
        assert found.status == "ok", found
        absent = detect_over_runner({"files": ["~/.nn-no-such-marker"]}, env={}, runner=probe)
        assert absent.status == "missing", absent
    finally:
        remote(f'rm -f "$HOME/{marker}"')


def test_a_name_with_spaces_survives_the_trip_there_and_back(tmp_path):
    """Пробелы и кавычка в имени не должны рассыпаться ни при заливке, ни в команде."""
    source = tmp_path / "моя запись (v2) it's.txt"
    source.write_text("one\ntwo\nthree\n", encoding="utf-8")
    out = tmp_path / "итог (копия).txt"

    ssh = transport()
    prepared = ssh.prepare(
        {"in": str(source), "out": str(out)}, host=host(), run_id="smoke-spaces", env={}
    )
    assert prepared.failure is None, prepared.failure

    command = render("wc -l < {in} > {out}", prepared.context)
    result = ssh.execute(command, host=host(), timeout_s=60, work_dir=str(tmp_path), env={})
    assert result.exit_code == 0, result.stderr

    assert ssh.collect() is None
    assert out.is_file(), "выход с пробелами в имени обязан вернуться"
    assert out.read_text(encoding="utf-8").strip() == "3"
    ssh.finish()

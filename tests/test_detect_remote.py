"""Детект на чужой машине: перевод девяти стратегий в POSIX sh и честность отказов."""

import pytest

from nn.detect import (
    BATCH_LIMIT,
    TRANSPORT_FAILURE,
    batch_script,
    detect_over_runner,
    shell_tests,
)


def commands(spec, **kwargs):
    return [command for command, _ in shell_tests(spec, **kwargs)]


def test_bin_becomes_command_v():
    assert commands({"bin": "whisper-cli"}) == ["command -v whisper-cli >/dev/null 2>&1"]


def test_tilde_is_expanded_by_the_remote_shell_not_by_us():
    """`~` обязан уехать как $HOME: домашняя директория там своя."""
    (command,) = commands({"files": ["~/Models/ggml.bin"]})
    assert command == 'test -e "$HOME/Models/ggml.bin"'
    assert "/Users/" not in command


def test_absolute_file_path_is_quoted():
    (command,) = commands({"files": ["/data/models/a b.bin"]})
    assert command == "test -e '/data/models/a b.bin'"


def test_glob_stays_unquoted_so_the_shell_expands_it():
    (command,) = commands({"glob": ["~/Models/*.gguf"]})
    assert command == 'set -- $HOME/Models/*.gguf; test -e "$1"'


def test_env_check_survives_set_u():
    (command,) = commands({"env": ["OPENAI_API_KEY"]})
    assert command == 'test -n "${OPENAI_API_KEY:-}"'


def test_python_uses_the_pinned_interpreter():
    (command,) = commands({"python": "mlx_audio"}, interpreter="/opt/venv/bin/python3")
    assert command.startswith("/opt/venv/bin/python3 -c ")
    assert "import mlx_audio" in command


def test_every_strategy_is_translatable():
    """Нетранслируемых стратегий быть не должно: иначе детект молча неполон."""
    spec = {
        "bin": "x",
        "files": ["/a"],
        "glob": ["/b/*"],
        "env": ["K"],
        "http": "http://127.0.0.1:8188/x",
        "python": "mod",
        "npm": "pkg",
        "docker": "img:latest",
        "brew": "formula",
    }
    assert len(shell_tests(spec)) == 9


def test_all_reasons_are_filled():
    for _, reason in shell_tests({"bin": "x", "files": ["/a"], "brew": "f"}):
        assert reason.strip()


def test_ok_when_every_test_passes():
    result = detect_over_runner({"bin": "sh"}, env={}, runner=lambda c, *, timeout: (0, "", ""))
    assert result.status == "ok"


def test_failing_test_names_itself():
    """Проверки идут одним скриптом, и код выхода указывает на конкретную из них."""
    calls: list[str] = []

    def runner(command, *, timeout):
        calls.append(command)
        return (2, "", "")  # провалилась вторая проверка — brew

    result = detect_over_runner({"bin": "sh", "brew": "ffmpeg"}, env={}, runner=runner)
    assert result.status == "missing"
    assert "ffmpeg" in result.reason
    assert len(calls) == 1
    assert "command -v sh" in calls[0] and "brew list" in calls[0]


@pytest.mark.parametrize("code", sorted(TRANSPORT_FAILURE))
def test_transport_failure_is_stale_not_missing(code):
    """Связь не установилась — про инструмент мы не узнали ничего."""
    result = detect_over_runner(
        {"bin": "whisper-cli"},
        env={},
        runner=lambda c, *, timeout: (
            code,
            "",
            "ssh: connect to host box port 22: Connection refused",
        ),
    )
    assert result.status == "stale"
    assert "refused" in result.reason.lower()
    assert "whisper-cli" not in result.reason


def test_timeout_is_stale_too():
    result = detect_over_runner(
        {"bin": "x"}, env={}, runner=lambda c, *, timeout: (124, "", "timeout")
    )
    assert result.status == "stale"


def test_missing_key_is_checked_against_the_host_env_only():
    """Ключ с этой машины не делает удалённого провайдера готовым."""
    result = detect_over_runner(
        {"bin": "sh"},
        requires_key=("REMOTE_KEY",),
        env={},
        runner=lambda c, *, timeout: (0, "", ""),
    )
    assert result.status == "needs-key"

    ok = detect_over_runner(
        {"bin": "sh"},
        requires_key=("REMOTE_KEY",),
        env={"REMOTE_KEY": "value"},
        runner=lambda c, *, timeout: (0, "", ""),
    )
    assert ok.status == "ok"


def test_empty_detect_is_missing():
    assert (
        detect_over_runner({}, env={}, runner=lambda c, *, timeout: (0, "", "")).status == "missing"
    )


def test_batch_puts_every_test_in_one_script():
    tests = shell_tests({"bin": "a", "files": ["/b"], "brew": "c"})
    script = batch_script(tests)
    assert script.count(" || exit") == 3
    assert script.splitlines()[0].endswith(" || exit 1")
    assert script.splitlines()[-1] == "exit 0"


def test_batched_detect_uses_a_single_call():
    calls: list[str] = []

    def runner(command, *, timeout):
        calls.append(command)
        return (0, "", "")

    spec = {"bin": "a", "files": ["/b", "/c"], "glob": ["/d/*"], "brew": "e"}
    assert detect_over_runner(spec, env={}, runner=runner).status == "ok"
    assert len(calls) == 1, "пять проверок — одно рукопожатие"


@pytest.mark.parametrize("failing", [1, 2, 3, 4, 5])
def test_exit_code_maps_back_to_the_right_reason(failing):
    """Номер провалившейся проверки не должен съезжать: причина обязана совпадать."""
    spec = {"bin": "thebin", "files": ["/one", "/two"], "glob": ["/three/*"], "brew": "thecask"}
    tests = shell_tests(spec)
    assert len(tests) == 5

    result = detect_over_runner(spec, env={}, runner=lambda c, *, timeout: (failing, "", ""))
    assert result.status == "missing"
    assert result.reason == tests[failing - 1][1]


def test_unexpected_exit_code_is_not_blamed_on_a_tool():
    """Код, которого мы не выдавали, — про канал, а не про инструмент."""
    result = detect_over_runner(
        {"bin": "x"}, env={}, runner=lambda c, *, timeout: (42, "", "something odd")
    )
    assert result.status == "stale"
    assert "odd" in result.reason


def test_too_many_tests_fall_back_to_one_call_each():
    """За пределом батча номер уже не влезает в код выхода — идём по одной."""
    spec = {"files": [f"/f{i}" for i in range(BATCH_LIMIT + 5)]}
    calls: list[str] = []

    def runner(command, *, timeout):
        calls.append(command)
        return (0, "", "")

    assert detect_over_runner(spec, env={}, runner=runner).status == "ok"
    assert len(calls) == BATCH_LIMIT + 5


def test_batch_limit_stays_below_the_reserved_codes():
    """Номер проверки не должен налезть на коды таймаута и отказа канала."""
    reserved = min(TRANSPORT_FAILURE | {124})
    assert reserved > BATCH_LIMIT

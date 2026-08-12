import pytest

from nn.errors import Exit, NnError
from nn.model import Host
from nn.transport import LocalTransport, ManualTransport, get_transport, resolve_env

LOCAL = Host(id="local", kind="local")
MANUAL_HOST = Host(id="winpc", kind="ssh", addr="winpc-cc", auto=False)


def test_local_transport_runs_command(tmp_path):
    transport = get_transport(LOCAL)
    result = transport.execute(
        "printf hello > out.txt", host=LOCAL, timeout_s=10, work_dir=str(tmp_path), env={}
    )
    assert result.exit_code == 0
    assert result.timed_out is False
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "hello"


def test_local_transport_captures_stderr_and_code(tmp_path):
    result = LocalTransport().execute(
        "echo boom >&2; exit 3", host=LOCAL, timeout_s=10, work_dir=str(tmp_path), env={}
    )
    assert result.exit_code == 3
    assert "boom" in result.stderr


def test_local_transport_marks_timeout(tmp_path):
    result = LocalTransport().execute(
        "sleep 5", host=LOCAL, timeout_s=1, work_dir=str(tmp_path), env={}
    )
    assert result.timed_out is True


def test_local_transport_injects_env(tmp_path):
    result = LocalTransport().execute(
        'printf %s "$NN_TEST_VAR"',
        host=LOCAL,
        timeout_s=10,
        work_dir=str(tmp_path),
        env={"NN_TEST_VAR": "injected"},
    )
    assert result.stdout.strip() == "injected"


def test_manual_transport_does_not_execute(tmp_path):
    result = ManualTransport().execute(
        "printf hello > out.txt",
        host=MANUAL_HOST,
        timeout_s=10,
        work_dir=str(tmp_path),
        env={},
    )
    assert result.exit_code == int(Exit.MANUAL)
    assert not (tmp_path / "out.txt").exists()
    assert "ssh winpc-cc" in result.command


def test_get_transport_respects_auto_false():
    assert isinstance(get_transport(MANUAL_HOST), ManualTransport)


def test_get_transport_manual_kind():
    assert isinstance(get_transport(Host(id="h", kind="manual")), ManualTransport)


def test_ssh_transport_not_available_yet():
    host = Host(id="mini", kind="ssh", addr="mac-mini", auto=True)
    with pytest.raises(NnError) as err:
        get_transport(host)
    assert err.value.code == Exit.BAD_DATA
    assert "фазе 6" in err.value.message


def test_resolve_env_reads_at_file(tmp_path):
    secret = tmp_path / "key.txt"
    secret.write_text("s3cret\n", encoding="utf-8")
    host = Host(id="mini", kind="ssh", addr="m", env={"KEY": f"@file:{secret}"})
    assert resolve_env(host, {})["KEY"] == "s3cret"


def test_resolve_env_missing_file_is_bad_data(tmp_path):
    host = Host(id="mini", kind="ssh", addr="m", env={"KEY": f"@file:{tmp_path}/absent"})
    with pytest.raises(NnError) as err:
        resolve_env(host, {})
    assert err.value.code == Exit.BAD_DATA


def test_resolve_env_plain_values_pass_through():
    host = Host(id="h", kind="local", env={"A": "1"})
    assert resolve_env(host, {"B": "2"}) == {"A": "1", "B": "2"}

from nn.detect import DetectResult, run_detect, which


def fake_runner_factory(mapping):
    def runner(command, *, timeout):
        for needle, result in mapping.items():
            if needle in command:
                return result
        return (127, "", "not found")

    return runner


def test_bin_found_via_path():
    assert run_detect({"bin": "echo"}) == DetectResult("ok", "")


def test_bin_missing():
    res = run_detect({"bin": "nn-definitely-not-a-binary"})
    assert res.status == "missing"
    assert "nn-definitely-not-a-binary" in res.reason


def test_files_all_must_exist(tmp_path):
    present = tmp_path / "m.bin"
    present.write_text("x", encoding="utf-8")
    assert run_detect({"files": [str(present)]}).status == "ok"
    res = run_detect({"files": [str(present), str(tmp_path / "nope.bin")]})
    assert res.status == "missing"
    assert "nope.bin" in res.reason


def test_glob_needs_one_match(tmp_path):
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "a.safetensors").write_text("x", encoding="utf-8")
    assert run_detect({"glob": [str(tmp_path / "models" / "*.safetensors")]}).status == "ok"
    assert run_detect({"glob": [str(tmp_path / "models" / "*.gguf")]}).status == "missing"


def test_env_keys_must_be_non_empty():
    assert run_detect({"env": ["K"]}, env={"K": "v"}).status == "ok"
    assert run_detect({"env": ["K"]}, env={"K": ""}).status == "missing"


def test_requires_key_missing_gives_needs_key():
    res = run_detect({"bin": "echo"}, requires_key=("SOME_API_KEY",), env={})
    assert res.status == "needs-key"
    assert "SOME_API_KEY" in res.reason


def test_http_probe_uses_runner():
    runner = fake_runner_factory({"127.0.0.1:8188": (0, "", "")})
    res = run_detect({"http": "http://127.0.0.1:8188/"}, runner=runner)
    assert res.status == "ok"


def test_http_probe_failure_is_missing():
    runner = fake_runner_factory({})
    res = run_detect({"http": "http://127.0.0.1:9999/"}, runner=runner)
    assert res.status == "missing"
    assert "не ответил" in res.reason


def test_python_module_strategy():
    runner = fake_runner_factory({"import mlx": (0, "", "")})
    assert run_detect({"python": "mlx"}, runner=runner).status == "ok"
    assert run_detect({"python": "absent_mod"}, runner=runner).status == "missing"


def test_python_module_checked_with_pinned_interpreter():
    """Регрессия: модуль проверялся системным python3, а не venv провайдера,
    поэтому скан считал обёртки со своим venv доступными до первого падения."""
    seen: list[str] = []

    def runner(command, *, timeout):
        seen.append(command)
        return (0, "", "")

    run_detect({"python": "mlx_audio"}, runner=runner, interpreter="/venv/bin/python3")
    assert seen == ['/venv/bin/python3 -c "import mlx_audio"']


def test_python_module_falls_back_to_system_interpreter():
    seen: list[str] = []

    def runner(command, *, timeout):
        seen.append(command)
        return (0, "", "")

    run_detect({"python": "json"}, runner=runner)
    assert seen == ['python3 -c "import json"']


def test_npm_docker_brew_strategies():
    runner = fake_runner_factory(
        {
            "npm ls": (0, "/x/node_modules/hyperframes\n", ""),
            "docker images": (0, "comfy:latest\n", ""),
            "brew list": (0, "ffmpeg\njq\n", ""),
        }
    )
    assert run_detect({"npm": "hyperframes"}, runner=runner).status == "ok"
    assert run_detect({"npm": "absent-pkg"}, runner=runner).status == "missing"
    assert run_detect({"docker": "comfy:latest"}, runner=runner).status == "ok"
    assert run_detect({"brew": "jq"}, runner=runner).status == "ok"
    assert run_detect({"brew": "nope"}, runner=runner).status == "missing"


def test_all_strategies_are_anded(tmp_path):
    res = run_detect({"bin": "echo", "files": [str(tmp_path / "absent")]})
    assert res.status == "missing"


def test_empty_spec_is_rejected():
    res = run_detect({})
    assert res.status == "missing"
    assert "пустой detect" in res.reason


def test_which_finds_known_locations(monkeypatch, tmp_path):
    fake_bin = tmp_path / ".local" / "bin" / "toolz"
    fake_bin.parent.mkdir(parents=True)
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_bin.chmod(0o755)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", "/nonexistent")
    assert which("toolz") == str(fake_bin)

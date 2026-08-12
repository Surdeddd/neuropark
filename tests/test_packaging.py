"""Упаковка плагина: манифесты валидны, скилл на месте, install.sh корректен."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from nn.errors import Exit

ROOT = Path(__file__).resolve().parents[1]


def test_plugin_manifest_is_valid_json():
    payload = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert payload["name"] == "neuropark"
    assert payload["description"]


def test_marketplace_manifest_points_at_plugin():
    payload = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    names = [item["name"] for item in payload["plugins"]]
    assert "neuropark" in names


def test_skill_has_frontmatter_with_triggers():
    text = (ROOT / "skills" / "nn" / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    head = text.split("---", 2)[1]
    assert "name: nn" in head
    assert "Triggers" in head
    for russian in ("транскриб", "озвуч", "картинк", "парк нейронок"):
        assert russian in head, russian
    for english in ("transcribe", "voice over", "generate image", "neural park"):
        assert english in head, english


def test_skill_documents_exit_codes_and_outcomes():
    text = (ROOT / "skills" / "nn" / "SKILL.md").read_text(encoding="utf-8")
    for token in ("success", "empty", "quota", "refused", "timeout", "crash"):
        assert token in text, token
    for code in ("`2`", "`3`", "`5`", "`6`", "`8`"):
        assert code in text, code


def test_skill_states_the_two_hard_rules():
    text = (ROOT / "skills" / "nn" / "SKILL.md").read_text(encoding="utf-8")
    assert "не подменяется молча" in text
    assert "не применяются" in text


def test_command_file_exists_and_references_skill():
    text = (ROOT / "commands" / "nn.md").read_text(encoding="utf-8")
    assert "$ARGUMENTS" in text
    assert "nn" in text


def test_install_script_is_executable_and_shellcheck_clean():
    script = ROOT / "install.sh"
    assert script.is_file()
    syntax = subprocess.run(
        ["bash", "-n", str(script)], capture_output=True, text=True, check=False
    )
    assert syntax.returncode == 0, syntax.stderr


def test_install_script_is_idempotent_about_symlink():
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "if [ -L" in text  # существующий симлинк не перезатирается


def test_no_autoschedule_left_anywhere():
    """Расписания и TG-алёрты выпилены осознанно: скан запускает человек."""
    for path in [*(ROOT / "src" / "nn").glob("*.py"), ROOT / "install.sh"]:
        text = path.read_text(encoding="utf-8")
        assert "launchctl" not in text, path
        assert "schtasks" not in text, path
        assert "notify-maxim" not in text, path


def test_readme_exists_in_both_languages():
    english = (ROOT / "README.md").read_text(encoding="utf-8")
    russian = (ROOT / "README.ru.md").read_text(encoding="utf-8")
    assert "README.ru.md" in english
    assert "README.md" in russian
    assert "one command to call any of them" in english.lower()
    assert "одна команда, чтобы позвать любую" in russian.lower()


def test_readmes_cover_the_same_sections():
    """Русская версия — полноценная, а не обрезок английской."""
    english = (ROOT / "README.md").read_text(encoding="utf-8")
    russian = (ROOT / "README.ru.md").read_text(encoding="utf-8")
    pairs = [
        ("## Quick start", "## Быстрый старт"),
        ("## How it works", "## Как это работает"),
        ("## Add a tool", "## Добавить нейронку"),
        ("## Chains", "## Цепочки"),
        ("## Orchestration", "## Оркестрация"),
        ("## Exit codes", "## Коды выхода"),
        ("## Language", "## Язык"),
        ("## Development", "## Разработка"),
        ("## License", "## Лицензия"),
    ]
    for en_section, ru_section in pairs:
        assert en_section in english, en_section
        assert ru_section in russian, ru_section


def test_license_file_exists():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in text


def test_memory_bank_follows_canonical_structure():
    """Каноническая структура Cline: шесть файлов с иерархией зависимостей.

    Банк локальный и лежит в .gitignore, поэтому на свежем клоне его нет —
    тогда проверять нечего. Если он есть, структура обязана быть канонической.
    """
    bank = ROOT / "MEMORY_BANK"
    if not bank.is_dir():
        pytest.skip("MEMORY_BANK локальный и в .gitignore — на клоне отсутствует")
    required = {
        "projectbrief.md",
        "productContext.md",
        "systemPatterns.md",
        "techContext.md",
        "activeContext.md",
        "progress.md",
    }
    present = {path.name for path in bank.glob("*.md")}
    assert required <= present, required - present


def test_memory_bank_is_gitignored():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "MEMORY_BANK" in ignore


def test_version_in_plugin_matches_cli():
    payload = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    cli = (ROOT / "src" / "nn" / "cli.py").read_text(encoding="utf-8")
    version = re.search(r'VERSION = "([^"]+)"', cli)
    assert version is not None
    assert payload["version"] == version.group(1)


def _declared_version() -> str:
    cli = (ROOT / "src" / "nn" / "cli.py").read_text(encoding="utf-8")
    version = re.search(r'VERSION = "([^"]+)"', cli)
    assert version is not None
    return version.group(1)


def test_pyproject_version_matches_cli():
    """Третье место с версией уже успело отстать один раз — теперь оно под тестом."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{_declared_version()}"' in text


def test_changelog_documents_the_current_version():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## {_declared_version()}" in text


def test_contributing_states_the_data_first_path():
    text = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "priors.json" in text
    assert "stdlib" in text
    for russian in ("Как участвовать", "мостика"):
        assert russian in text, russian


def test_hook_manifest_wires_session_start_through_plugin_root():
    payload = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    entries = payload["hooks"]["SessionStart"]
    commands = [hook["command"] for entry in entries for hook in entry["hooks"]]
    assert commands, "SessionStart без команд"
    for command in commands:
        assert "${CLAUDE_PLUGIN_ROOT}" in command, command
        assert "session-start.sh" in command


def test_hook_scripts_are_executable_and_syntax_clean():
    for name in ("session-start.sh", "pre-commit"):
        script = ROOT / "hooks" / name
        assert script.is_file(), name
        assert script.stat().st_mode & 0o111, f"{name} не исполняемый"
        syntax = subprocess.run(
            ["bash", "-n", str(script)], capture_output=True, text=True, check=False
        )
        assert syntax.returncode == 0, syntax.stderr


def test_session_start_hook_is_silent_when_the_park_is_healthy(tmp_path):
    """Хук, который здоровается каждую сессию, начинают игнорировать."""
    state = tmp_path / "state"
    data = tmp_path / "data"
    (data / "providers").mkdir(parents=True)
    (data / "providers" / "x.json").write_text("{}", encoding="utf-8")
    state.mkdir()
    (state / "registry.host.json").write_text("{}", encoding="utf-8")
    result = subprocess.run(
        ["bash", str(ROOT / "hooks" / "session-start.sh")],
        capture_output=True,
        text=True,
        check=False,
        env={
            "HOME": str(tmp_path),
            "NN_STATE": str(state),
            "NN_HOME": str(data),
            "PATH": "/usr/bin:/bin",
        },
    )
    assert result.returncode == 0
    assert result.stdout == "", result.stdout


def test_session_start_hook_speaks_when_nothing_was_scanned(tmp_path):
    data = tmp_path / "data"
    (data / "providers").mkdir(parents=True)
    (data / "providers" / "x.json").write_text("{}", encoding="utf-8")
    result = subprocess.run(
        ["bash", str(ROOT / "hooks" / "session-start.sh")],
        capture_output=True,
        text=True,
        check=False,
        env={
            "HOME": str(tmp_path),
            "NN_STATE": str(tmp_path / "empty"),
            "NN_HOME": str(data),
            "PATH": "/usr/bin:/bin",
        },
    )
    assert result.returncode == 0
    assert "nn scan" in result.stdout


def test_pre_commit_hook_runs_the_same_checks_as_make_check():
    text = (ROOT / "hooks" / "pre-commit").read_text(encoding="utf-8")
    for check in ("ruff check", "ruff format --check", "mypy --strict", "not smoke"):
        assert check in text, check
    assert "--no-verify" in text  # выход всегда назван вслух


def test_ci_covers_both_platforms_and_a_cold_start():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for token in ("ubuntu-latest", "macos-latest", "3.11", "3.13"):
        assert token in text, token
    assert "nn init" in text  # холодный старт на пустой машине
    assert "NN_LANG=ru" in text


def test_issue_templates_include_the_data_first_path():
    templates = ROOT / ".github" / "ISSUE_TEMPLATE"
    names = {path.name for path in templates.glob("*.yml")}
    assert {"bug_report.yml", "feature_request.yml", "add_tool.yml", "config.yml"} <= names
    assert "priors.json" in (templates / "add_tool.yml").read_text(encoding="utf-8")


def test_pull_request_template_asks_for_evidence():
    text = (ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md").read_text(encoding="utf-8")
    assert "make check" in text
    assert "NN_LANG=ru" in text


def test_makefile_exposes_setup_and_hooks():
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    for target in ("help:", "setup:", "check:", "hooks:", "smoke-fast:", "clean:"):
        assert target in text, target


def test_installer_offers_the_hook_without_forcing_it():
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "pre-commit" in text
    assert "NN_INSTALL_HOOKS" in text  # неинтерактивный путь тоже назван


def test_launcher_refuses_old_python_with_a_clear_message(tmp_path):
    """На macOS первым в PATH часто стоит системный 3.9 — раньше это давало ImportError."""
    fake = tmp_path / "bin"
    fake.mkdir()
    stub = fake / "python3"
    # Заглушка ведёт себя как python 3.9: проверку версии не проходит,
    # а --version печатает старый номер, который nn обязан назвать в сообщении.
    stub.write_text(
        '#!/bin/sh\ncase "$1" in -c) exit 1 ;; esac\necho 3.9.6\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)
    result = subprocess.run(
        [str(ROOT / "bin" / "nn"), "--version"],
        capture_output=True,
        text=True,
        check=False,
        # /usr/bin и /bin оставлены только ради bash: настоящего python 3.11+ там нет.
        env={"PATH": f"{fake}:/usr/bin:/bin", "NN_LANG": "en", "NN_PYTHON": str(stub)},
    )
    assert result.returncode == int(Exit.BAD_DATA), result
    assert "3.11+" in result.stderr
    assert "NN_PYTHON" in result.stderr


def test_launcher_is_not_fooled_by_a_command_that_always_succeeds():
    """Проверка смотрит на ответ, а не на код возврата: /bin/echo выходит нулём на всё."""
    result = subprocess.run(
        [str(ROOT / "bin" / "nn"), "--version"],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "NN_LANG": "en", "NN_PYTHON": "/bin/echo"},
    )
    assert result.returncode == int(Exit.BAD_DATA), result
    assert "3.11+" in result.stderr


def test_launcher_names_a_missing_interpreter():
    result = subprocess.run(
        [str(ROOT / "bin" / "nn"), "--version"],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "NN_LANG": "en", "NN_PYTHON": "/nope/python"},
    )
    assert result.returncode == int(Exit.BAD_DATA), result
    assert "no such interpreter" in result.stderr


def test_launcher_prefers_a_working_interpreter(tmp_path):
    """Битый python3 в PATH не должен ломать nn, если рядом есть годный."""
    fake = tmp_path / "bin"
    fake.mkdir()
    stub = fake / "python3"
    stub.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    stub.chmod(0o755)
    good = shutil.which("python3.13") or shutil.which("python3.12") or shutil.which("python3.11")
    if good is None:
        pytest.skip("на этой машине нет отдельного python3.11+ рядом с системным")
    env = dict(os.environ)
    env["PATH"] = f"{fake}:{Path(good).parent}:/usr/bin:/bin"
    result = subprocess.run(
        [str(ROOT / "bin" / "nn"), "--version"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("nn ")

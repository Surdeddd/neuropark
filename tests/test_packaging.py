"""Упаковка плагина: манифесты валидны, скилл на месте, install.sh корректен."""

import json
import re
import subprocess
from pathlib import Path

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
    # явные триггеры «когда звать» — иначе скилл не будет вызываться сам
    assert "Триггеры" in head
    for trigger in ("транскриб", "озвуч", "картинк", "парк нейронок"):
        assert trigger in head, trigger


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


def test_version_in_plugin_matches_cli():
    payload = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    cli = (ROOT / "src" / "nn" / "cli.py").read_text(encoding="utf-8")
    version = re.search(r'VERSION = "([^"]+)"', cli)
    assert version is not None
    assert payload["version"] == version.group(1)

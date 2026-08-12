"""Настоящий git, без сети: создаём репо в tmp и работаем с ним."""

import subprocess
from pathlib import Path

import pytest

from nn.errors import Exit, NnError
from nn.worktree import create, ensure_ready, extract_patch, finish, remove


def git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    git(["init", "-q"], root)
    git(["config", "user.name", "Test"], root)
    git(["config", "user.email", "test@example.com"], root)
    (root / "file.txt").write_text("исходник\n", encoding="utf-8")
    git(["add", "."], root)
    git(["commit", "-q", "-m", "первый"], root)
    return root


def test_ensure_ready_passes_on_clean_repo(repo):
    ensure_ready(repo)


def test_ensure_ready_rejects_non_git(tmp_path, monkeypatch):
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(NnError) as err:
        ensure_ready(plain)
    assert err.value.code == Exit.PROVIDER_FAILED


def test_ensure_ready_rejects_repo_mid_merge(repo):
    (Path(repo) / ".git" / "MERGE_HEAD").write_text("deadbeef\n", encoding="utf-8")
    with pytest.raises(NnError) as err:
        ensure_ready(repo)
    assert "MERGE_HEAD" in err.value.message


def test_create_makes_isolated_copy(repo):
    worktree = create(repo, "run-1")
    assert (worktree / "file.txt").read_text(encoding="utf-8") == "исходник\n"
    remove(repo, worktree)


def test_changes_in_worktree_do_not_touch_original(repo):
    worktree = create(repo, "run-2")
    (worktree / "file.txt").write_text("правка агента\n", encoding="utf-8")
    assert (repo / "file.txt").read_text(encoding="utf-8") == "исходник\n"
    remove(repo, worktree)


def test_extract_patch_returns_diff(repo):
    worktree = create(repo, "run-3")
    (worktree / "file.txt").write_text("правка агента\n", encoding="utf-8")
    patch = extract_patch(repo, worktree, "run-3")
    assert patch is not None
    body = patch.read_text(encoding="utf-8")
    assert "правка агента" in body
    assert "-исходник" in body
    remove(repo, worktree)


def test_extract_patch_sees_new_files(repo):
    worktree = create(repo, "run-4")
    (worktree / "новый.py").write_text("print(1)\n", encoding="utf-8")
    patch = extract_patch(repo, worktree, "run-4")
    assert patch is not None
    assert "новый.py" in patch.read_text(encoding="utf-8")
    remove(repo, worktree)


def test_no_changes_gives_no_patch(repo):
    worktree = create(repo, "run-5")
    assert extract_patch(repo, worktree, "run-5") is None
    remove(repo, worktree)


def test_finish_removes_worktree_and_returns_patch(repo):
    worktree = create(repo, "run-6")
    (worktree / "file.txt").write_text("ещё правка\n", encoding="utf-8")
    result = finish(repo, worktree, "run-6")
    assert result.changed is True
    assert result.patch is not None
    assert not worktree.exists()


def test_finish_can_keep_worktree(repo):
    worktree = create(repo, "run-7")
    (worktree / "file.txt").write_text("правка\n", encoding="utf-8")
    result = finish(repo, worktree, "run-7", keep=True)
    assert worktree.exists()
    assert result.changed is True
    remove(repo, worktree)


def test_patch_is_never_applied_to_original(repo):
    """Главное правило фазы 5: мерж — решение человека, движок не применяет."""
    worktree = create(repo, "run-8")
    (worktree / "file.txt").write_text("не должно попасть в репо\n", encoding="utf-8")
    finish(repo, worktree, "run-8")
    assert (repo / "file.txt").read_text(encoding="utf-8") == "исходник\n"
    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=repo, capture_output=True, text=True, check=True
    )
    assert len(log.stdout.strip().splitlines()) == 1  # ни одного нового коммита

"""Изолированный git worktree для запусков, которые правят репозиторий.

Правило без исключений: патч возвращается артефактом и НИКОГДА не применяется
и не коммитится. Мерж — решение человека.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from nn.errors import Exit, NnError
from nn.paths import state_dir

BUSY_MARKERS = ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD")


@dataclass(frozen=True)
class WorktreeResult:
    path: Path
    patch: Path | None
    changed: bool


def _git(args: list[str], *, cwd: Path) -> tuple[int, str, str]:
    # core.quotePath=false обязателен: иначе git пишет кириллические имена файлов
    # восьмеричными кодами и патч становится нечитаемым для человека
    done = subprocess.run(
        ["git", "-c", "core.quotePath=false", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    return done.returncode, done.stdout, done.stderr


def worktrees_dir() -> Path:
    path = state_dir() / "worktrees"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_ready(repo: Path) -> None:
    """Репозиторий должен быть git и не в середине rebase/merge."""
    code, out, _ = _git(["rev-parse", "--git-dir"], cwd=repo)
    if code != 0:
        raise NnError(Exit.PROVIDER_FAILED, f"{repo} не git-репозиторий — worktree не создать")
    raw = Path(out.strip())
    git_dir = raw if raw.is_absolute() else (repo / raw).resolve()
    for marker in BUSY_MARKERS:
        if (git_dir / marker).exists():
            raise NnError(
                Exit.PROVIDER_FAILED,
                f"репозиторий в состоянии {marker} — сначала доведи операцию до конца",
            )
    code, _, _ = _git(["rev-parse", "HEAD"], cwd=repo)
    if code != 0:
        raise NnError(Exit.PROVIDER_FAILED, f"{repo}: нет ни одного коммита, worktree не от чего")


def create(repo: Path, run_id: str) -> Path:
    ensure_ready(repo)
    path = worktrees_dir() / run_id
    code, _, err = _git(["worktree", "add", str(path), "HEAD", "--detach"], cwd=repo)
    if code != 0:
        raise NnError(Exit.PROVIDER_FAILED, f"не удалось создать worktree: {err.strip()}")
    return path


def extract_patch(repo: Path, worktree: Path, run_id: str) -> Path | None:
    """Патч всего, что изменилось в worktree. None — если изменений нет."""
    code, _, err = _git(["add", "-A"], cwd=worktree)
    if code != 0:
        raise NnError(Exit.PROVIDER_FAILED, f"git add в worktree упал: {err.strip()}")
    code, diff, err = _git(["diff", "--cached", "HEAD"], cwd=worktree)
    if code != 0:
        raise NnError(Exit.PROVIDER_FAILED, f"git diff в worktree упал: {err.strip()}")
    if not diff.strip():
        return None
    path = state_dir() / "out" / f"{run_id}.patch"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(diff, encoding="utf-8")
    return path


def remove(repo: Path, worktree: Path) -> None:
    _git(["worktree", "remove", "--force", str(worktree)], cwd=repo)


def finish(repo: Path, worktree: Path, run_id: str, *, keep: bool = False) -> WorktreeResult:
    patch = extract_patch(repo, worktree, run_id)
    if not keep:
        remove(repo, worktree)
    return WorktreeResult(path=worktree, patch=patch, changed=patch is not None)

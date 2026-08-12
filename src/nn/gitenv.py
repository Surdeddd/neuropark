"""Гигиена git-окружения для всего, что nn запускает.

Внутри git-хука git экспортирует GIT_DIR, GIT_INDEX_FILE и родню. Дочерний процесс
с cwd=другой-репозиторий всё равно уйдёт туда, куда указывают переменные, а не туда,
где стоит. Из-за этого первый же коммит через собственный pre-commit уронил 13 тестов
worktree: git внутри временного репозитория работал с репозиторием nn.
"""

from __future__ import annotations

import os

GIT_ENV_OVERRIDES = (
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_WORK_TREE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_PREFIX",
    "GIT_COMMON_DIR",
    "GIT_INDEX_VERSION",
)


def clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    environ = {k: v for k, v in os.environ.items() if k not in GIT_ENV_OVERRIDES}
    if extra:
        environ.update(extra)
    return environ

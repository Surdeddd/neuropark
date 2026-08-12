from __future__ import annotations

import glob as globlib
import os
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from nn.i18n import bi

EXTRA_BIN_DIRS = (
    "~/.local/bin",
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "~/.grok/bin",
    "~/.kimi-code/bin",
)


class Runner(Protocol):
    def __call__(self, command: str, *, timeout: float) -> tuple[int, str, str]: ...


def shell_runner(command: str, *, timeout: float) -> tuple[int, str, str]:
    try:
        done = subprocess.run(  # noqa: S602
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return (124, "", "timeout")
    return (done.returncode, done.stdout, done.stderr)


def which(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for directory in EXTRA_BIN_DIRS:
        candidate = Path(directory).expanduser() / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


@dataclass(frozen=True)
class DetectResult:
    status: str
    reason: str


def _glob_matches(pattern: str) -> bool:
    """Есть ли хоть одно совпадение по абсолютному шаблону.

    Намеренно используется glob.glob, а не Path.glob (ruff PTH207): на macOS
    Path("/").glob("var/...") не проходит промежуточный симлинк /var → private/var,
    поэтому даёт пустой результат и тратит на это ~20 секунд. glob.glob отвечает
    правильно за 0.01s. Проверено на python 3.12 и 3.14, 2026-08-12.
    """
    return bool(globlib.glob(str(Path(pattern).expanduser())))  # noqa: PTH207


def run_detect(
    spec: Mapping[str, Any],
    *,
    requires_key: tuple[str, ...] = (),
    env: Mapping[str, str] | None = None,
    runner: Runner = shell_runner,
) -> DetectResult:
    environ = os.environ if env is None else env
    for key in requires_key:
        if not environ.get(key):
            return DetectResult(
                "needs-key", bi(f"env variable {key} is not set", f"нет переменной окружения {key}")
            )
    if not spec:
        return DetectResult("missing", bi("empty detect", "пустой detect"))

    name = spec.get("bin")
    if name and which(str(name)) is None:
        return DetectResult("missing", bi(f"binary {name} not found", f"бинарь {name} не найден"))

    for raw in spec.get("files") or ():
        path = Path(str(raw)).expanduser()
        if not path.exists():
            return DetectResult(
                "missing", bi(f"file {path} is missing", f"файл {path} отсутствует")
            )

    for pattern in spec.get("glob") or ():
        if not _glob_matches(str(pattern)):
            return DetectResult(
                "missing",
                bi(f"pattern {pattern} matched nothing", f"шаблон {pattern} не дал совпадений"),
            )

    for key in spec.get("env") or ():
        if not environ.get(str(key)):
            return DetectResult(
                "missing", bi(f"env variable {key} is empty", f"переменная окружения {key} пуста")
            )

    url = spec.get("http")
    if url:
        code, _, _ = runner(f"curl -fsS -m 3 -o /dev/null {url}", timeout=5)
        if code != 0:
            return DetectResult(
                "missing", bi(f"endpoint {url} did not answer", f"эндпоинт {url} не ответил")
            )

    module = spec.get("python")
    if module:
        code, _, _ = runner(f'python3 -c "import {module}"', timeout=15)
        if code != 0:
            return DetectResult(
                "missing",
                bi(
                    f"python module {module} does not import",
                    f"python-модуль {module} не импортируется",
                ),
            )

    package = spec.get("npm")
    if package:
        code, out, _ = runner("npm ls -g --depth=0 --parseable", timeout=30)
        if code != 0 or str(package) not in out:
            return DetectResult(
                "missing",
                bi(
                    f"npm package {package} is not installed globally",
                    f"npm-пакет {package} не установлен глобально",
                ),
            )

    image = spec.get("docker")
    if image:
        code, out, _ = runner("docker images --format '{{.Repository}}:{{.Tag}}'", timeout=15)
        if code != 0 or str(image) not in out:
            return DetectResult(
                "missing",
                bi(f"docker image {image} is missing", f"docker-образ {image} отсутствует"),
            )

    formula = spec.get("brew")
    if formula:
        code, out, _ = runner("brew list --formula -1", timeout=30)
        if code != 0 or str(formula) not in out.split():
            return DetectResult(
                "missing",
                bi(
                    f"brew formula {formula} is not installed",
                    f"формула brew {formula} не установлена",
                ),
            )

    return DetectResult("ok", "")

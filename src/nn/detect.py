from __future__ import annotations

import glob as globlib
import os
import shlex
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from nn.i18n import bi

# 255 — ssh не смог соединиться, 127 — самого ssh нет. И то и другое говорит
# о канале, а не о проверяемом инструменте.
TRANSPORT_FAILURE = frozenset({127, 255})

# До этого числа проверок номер провалившейся передаётся кодом выхода. Предел
# оставлен заведомо ниже 124 и 127: там начинаются коды таймаута и «нет ssh».
BATCH_LIMIT = 50

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


def glob_paths(pattern: str) -> list[Path]:
    """Единственное место в проекте, где раскрывается файловый шаблон.

    Намеренно glob.glob, а не Path.glob (ruff PTH207): на macOS
    Path("/").glob("var/...") не проходит промежуточный симлинк /var → private/var,
    поэтому даёт пустой результат и тратит на это ~20 секунд. glob.glob отвечает
    правильно за 0.01s. Проверено на python 3.12 и 3.14, 2026-08-12.

    Функция общая именно поэтому: ту же граблю я один раз уже вылечил здесь,
    а потом переизобрёл в nn.init. Один вход — один предохранитель.
    """
    expanded = str(Path(pattern).expanduser())
    return [Path(found) for found in globlib.glob(expanded)]  # noqa: PTH207


def _glob_matches(pattern: str) -> bool:
    return bool(glob_paths(pattern))


def _remote_path(raw: str) -> str:
    """`~/x` на той стороне раскрывает её шелл, а не наш: `~` уедет как $HOME."""
    text = str(raw)
    if text.startswith("~/"):
        return f'"$HOME/{text[2:]}"'
    return shlex.quote(text)


def shell_tests(
    spec: Mapping[str, Any], *, interpreter: str | None = None
) -> list[tuple[str, str]]:
    """Тот же детект, но выраженный командами POSIX sh — для чужой машины.

    Локальная проверка остаётся питоновской: она точнее (например, знает про
    каталоги вне PATH, куда ставятся агентские CLI). А на удалённой машине
    единственный доступный язык — шелл, и все девять стратегий в него ложатся.
    """
    tests: list[tuple[str, str]] = []

    name = spec.get("bin")
    if name:
        tests.append(
            (
                f"command -v {shlex.quote(str(name))} >/dev/null 2>&1",
                bi(f"binary {name} not found", f"бинарь {name} не найден"),
            )
        )

    for raw in spec.get("files") or ():
        tests.append(
            (
                f"test -e {_remote_path(str(raw))}",
                bi(f"file {raw} is missing", f"файл {raw} отсутствует"),
            )
        )

    for pattern in spec.get("glob") or ():
        # Шаблон нельзя кавычить целиком, иначе шелл его не раскроет.
        expanded = str(pattern)
        expanded = f"$HOME/{expanded[2:]}" if expanded.startswith("~/") else expanded
        tests.append(
            (
                f'set -- {expanded}; test -e "$1"',
                bi(f"pattern {pattern} matched nothing", f"шаблон {pattern} не дал совпадений"),
            )
        )

    for key in spec.get("env") or ():
        tests.append(
            (
                f'test -n "${{{key}:-}}"',
                bi(f"env variable {key} is empty", f"переменная окружения {key} пуста"),
            )
        )

    url = spec.get("http")
    if url:
        tests.append(
            (
                f"curl -fsS -m 3 -o /dev/null {shlex.quote(str(url))}",
                bi(f"endpoint {url} did not answer", f"эндпоинт {url} не ответил"),
            )
        )

    module = spec.get("python")
    if module:
        python = interpreter or "python3"
        tests.append(
            (
                f"{shlex.quote(python)} -c {shlex.quote(f'import {module}')}",
                bi(
                    f"python module {module} does not import",
                    f"python-модуль {module} не импортируется",
                ),
            )
        )

    package = spec.get("npm")
    if package:
        tests.append(
            (
                f"npm ls -g --depth=0 --parseable | grep -q {shlex.quote(str(package))}",
                bi(
                    f"npm package {package} is not installed globally",
                    f"npm-пакет {package} не установлен глобально",
                ),
            )
        )

    image = spec.get("docker")
    if image:
        tests.append(
            (
                f"docker image inspect {shlex.quote(str(image))} >/dev/null 2>&1",
                bi(f"docker image {image} is missing", f"docker-образ {image} отсутствует"),
            )
        )

    formula = spec.get("brew")
    if formula:
        tests.append(
            (
                f"brew list --formula -1 | grep -qx {shlex.quote(str(formula))}",
                bi(
                    f"brew formula {formula} is not installed",
                    f"формула brew {formula} не установлена",
                ),
            )
        )

    return tests


def batch_script(tests: list[tuple[str, str]]) -> str:
    """Все проверки одним скриптом: код выхода — номер первой не прошедшей.

    Каждый ssh-коннект стоит десятки миллисекунд даже по локальной петле, а по сети
    сотни. Пять провайдеров по три стратегии — это пятнадцать рукопожатий на каждый
    `nn scan`, то есть секунды на пустом месте.
    """
    lines = [f"{{ {command}; }} || exit {index}" for index, (command, _) in enumerate(tests, 1)]
    lines.append("exit 0")
    return "\n".join(lines)


def detect_over_runner(
    spec: Mapping[str, Any],
    *,
    requires_key: tuple[str, ...] = (),
    env: Mapping[str, str],
    runner: Runner,
    interpreter: str | None = None,
    timeout: float = 30,
) -> DetectResult:
    """Детект целиком на чужой машине: каждая стратегия — команда через runner.

    Ключи сверяются с тем окружением, которое та машина реально увидит при
    прогоне (`host.env`), а не с нашим: раньше сюда затекал локальный os.environ,
    и провайдер на удалённом хосте считался готовым из-за ключа на этой машине.
    """
    for key in requires_key:
        if not env.get(key):
            return DetectResult(
                "needs-key", bi(f"env variable {key} is not set", f"нет переменной окружения {key}")
            )
    if not spec:
        return DetectResult("missing", bi("empty detect", "пустой detect"))

    tests = shell_tests(spec, interpreter=interpreter)
    if not tests:
        return DetectResult("missing", bi("empty detect", "пустой detect"))

    def unreachable(err: str) -> DetectResult:
        # Связь не установилась — про инструмент мы так ничего и не узнали.
        # Раньше это выдавалось как «бинарь не найден», то есть врало о причине.
        detail = err.strip().splitlines()[-1][:120] if err.strip() else ""
        return DetectResult(
            "stale",
            bi(
                f"host did not answer: {detail}" if detail else "host did not answer",
                f"хост не ответил: {detail}" if detail else "хост не ответил",
            ),
        )

    timed_out = DetectResult("stale", bi("detect timed out", "детект не успел ответить"))

    if len(tests) <= BATCH_LIMIT:
        code, _, err = runner(batch_script(tests), timeout=timeout)
        if code == 124:
            return timed_out
        if code in TRANSPORT_FAILURE:
            return unreachable(err)
        if code == 0:
            return DetectResult("ok", "")
        if 1 <= code <= len(tests):
            return DetectResult("missing", tests[code - 1][1])
        # Скрипт ответил кодом, которого мы не выдавали: это не отказ инструмента.
        return unreachable(err)

    for command, reason in tests:
        code, _, err = runner(command, timeout=timeout)
        if code == 124:
            return timed_out
        if code in TRANSPORT_FAILURE:
            return unreachable(err)
        if code != 0:
            return DetectResult("missing", reason)
    return DetectResult("ok", "")


def run_detect(
    spec: Mapping[str, Any],
    *,
    requires_key: tuple[str, ...] = (),
    env: Mapping[str, str] | None = None,
    runner: Runner = shell_runner,
    interpreter: str | None = None,
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
        python = interpreter or "python3"
        code, _, _ = runner(f'{python} -c "import {module}"', timeout=15)
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

from __future__ import annotations

import platform
import re
import shlex
from collections.abc import Mapping
from pathlib import Path

from nn.errors import Exit, NnError
from nn.i18n import bi
from nn.model import Host, Provider
from nn.paths import expand

_NAME_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_.]*)\}")

PATH_NAMES = frozenset({"in", "out", "out_base", "tmp", "dir", "prompt_file"})


def os_key(system: str | None = None) -> str:
    name = (system or platform.system()).lower()
    if name.startswith("darwin"):
        return "darwin"
    if name.startswith("win"):
        return "win"
    return "linux"


def pick(templates: Mapping[str, str], *, system: str | None = None) -> str | None:
    key = os_key(system)
    if key in templates:
        return templates[key]
    return templates.get("")


def build_context(
    provider: Provider,
    host: Host,
    *,
    in_path: str | None,
    out_path: str | None,
    tmp_prefix: str,
    work_dir: str,
    prompt_file: str | None = None,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    context: dict[str, str] = {
        "in": in_path or "",
        "out": out_path or "",
        "out_base": str(Path(out_path).with_suffix("")) if out_path else "",
        "tmp": tmp_prefix,
        "dir": work_dir,
        "prompt_file": prompt_file or "",
    }
    for key, value in provider.vars.items():
        context[key] = expand(value)
    for key, value in host.paths.items():
        context[f"host.paths.{key}"] = value
    if extra:
        context.update(extra)
    return context


def needs_quoting(name: str) -> bool:
    """Пути, которые подставляет сам nn, а не автор манифеста.

    Их значения приходят от пользователя (имя файла может быть каким угодно) и
    обязаны попасть в команду одним аргументом. Всё остальное — `vars` и
    `host.paths.*` — пишет автор манифеста: там может лежать набор флагов, и
    кавычить его нельзя.
    """
    return name in PATH_NAMES or name.startswith("extra")


def render(template: str, context: Mapping[str, str]) -> str:
    """Подстановка в шаблон команды с экранированием путей.

    Без экранирования `nn run transcribe "my clip.wav"` разваливался на два
    аргумента и падал с кодом 254: команда собирается строкой для шелла, а имена
    файлов у людей с пробелами, скобками и кавычками — обычное дело.
    """

    def sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in context:
            raise NnError(
                Exit.BAD_DATA,
                bi(
                    f"template refers to an unknown variable {{{name}}}",
                    f"шаблон ссылается на неизвестную переменную {{{name}}}",
                ),
            )
        value = context[name]
        if not needs_quoting(name) or not value:
            return value
        return shlex.quote(value)

    return _NAME_RE.sub(sub, template)

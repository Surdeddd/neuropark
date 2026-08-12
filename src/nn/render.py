from __future__ import annotations

import platform
import re
from collections.abc import Mapping
from pathlib import Path

from nn.errors import Exit, NnError
from nn.model import Host, Provider
from nn.paths import expand

_NAME_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_.]*)\}")


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


def render(template: str, context: Mapping[str, str]) -> str:
    def sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in context:
            raise NnError(
                Exit.BAD_DATA,
                f"шаблон ссылается на неизвестную переменную {{{name}}}",
            )
        return context[name]

    return _NAME_RE.sub(sub, template)

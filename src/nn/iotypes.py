from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from nn.errors import Exit, NnError
from nn.model import Capability

Types = Mapping[str, tuple[str, ...]]


def type_of(path: str, types: Types) -> str:
    ext = Path(path).suffix.lstrip(".").lower()
    if not ext:
        raise NnError(Exit.BAD_IO, f"у входа {path} нет расширения — тип не определить")
    for name, exts in types.items():
        if ext in exts:
            return name
    raise NnError(Exit.BAD_IO, f"расширение .{ext} не описано в capabilities.json (types)")


def output_type(cap: Capability, in_type: str) -> str:
    return in_type if cap.out == "same" else cap.out


def accepts(provider_in: tuple[str, ...], in_type: str) -> bool:
    return in_type in provider_in


def check_extra(cap: Capability, extra_paths: tuple[str, ...], types: Types) -> None:
    if not cap.extra:
        return
    got = [type_of(path, types) for path in extra_paths]
    for needed in cap.extra:
        if needed not in got:
            raise NnError(
                Exit.BAD_IO,
                f"capability {cap.name} требует дополнительный вход типа {needed}"
                f" (передано: {got or 'ничего'}) — используй --extra",
            )


def ext_for(type_name: str, types: Types) -> str:
    exts = types.get(type_name)
    if not exts:
        raise NnError(Exit.BAD_IO, f"тип {type_name} не описан в capabilities.json (types)")
    return exts[0]

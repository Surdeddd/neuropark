from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TypeVar

from nn.errors import Exit, NnError
from nn.model import Bridge, Capability, Host, Provider, Recipe
from nn.paths import data_dir
from nn.schema import parse_bridge, parse_capabilities, parse_host, parse_provider, parse_recipe


@dataclass(frozen=True)
class Catalog:
    providers: dict[str, Provider]
    hosts: dict[str, Host]
    capabilities: dict[str, Capability]
    types: dict[str, tuple[str, ...]]
    bridges: dict[str, Bridge]
    recipes: dict[str, Recipe]


class HasId(Protocol):
    @property
    def id(self) -> str: ...


T = TypeVar("T", bound=HasId)


def _read(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NnError(Exit.BAD_DATA, f"{path}: невалидный JSON — {exc}") from exc
    if not isinstance(payload, dict):
        raise NnError(Exit.BAD_DATA, f"{path}: ожидался объект JSON")
    return payload


def _load_dir(root: Path, sub: str, parse: Callable[..., T]) -> dict[str, T]:
    out: dict[str, T] = {}
    directory = root / sub
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.json")):
        item = parse(_read(path), source=str(path.relative_to(root)))
        if item.id != path.stem:
            raise NnError(Exit.BAD_DATA, f"{path}: имя файла не совпадает с id ({item.id})")
        if item.id in out:
            raise NnError(Exit.BAD_DATA, f"{path}: дубль id {item.id}")
        out[item.id] = item
    return out


def load_catalog(root: Path | None = None) -> Catalog:
    base = root or data_dir()
    caps_path = base / "capabilities.json"
    if not caps_path.is_file():
        raise NnError(Exit.BAD_DATA, f"{caps_path} отсутствует")
    caps, types = parse_capabilities(_read(caps_path))
    hosts = _load_dir(base, "hosts", parse_host)
    if "local" not in hosts:
        raise NnError(Exit.BAD_DATA, "hosts/local.json отсутствует: нужен хост local")
    return Catalog(
        providers=_load_dir(base, "providers", parse_provider),
        hosts=hosts,
        capabilities=caps,
        types=types,
        bridges=_load_dir(base, "bridges", parse_bridge),
        recipes=_load_dir(base, "recipes", parse_recipe),
    )

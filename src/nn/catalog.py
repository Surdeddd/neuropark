from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TypeVar

from nn.errors import Exit, NnError
from nn.i18n import bi
from nn.model import Bridge, Capability, Host, Provider, Recipe, RolesConfig
from nn.paths import data_dir, state_dir, user_data_dir
from nn.schema import (
    parse_bridge,
    parse_capabilities,
    parse_host,
    parse_provider,
    parse_recipe,
    parse_roles,
)


@dataclass(frozen=True)
class Catalog:
    providers: dict[str, Provider]
    hosts: dict[str, Host]
    capabilities: dict[str, Capability]
    types: dict[str, tuple[str, ...]]
    bridges: dict[str, Bridge]
    recipes: dict[str, Recipe]
    roles: RolesConfig = RolesConfig()


class HasId(Protocol):
    @property
    def id(self) -> str: ...


T = TypeVar("T", bound=HasId)


def _read(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NnError(
            Exit.BAD_DATA, bi(f"{path}: invalid JSON — {exc}", f"{path}: невалидный JSON — {exc}")
        ) from exc
    if not isinstance(payload, dict):
        raise NnError(
            Exit.BAD_DATA,
            bi(f"{path}: a JSON object was expected", f"{path}: ожидался объект JSON"),
        )
    return payload


def _load_dir(root: Path, sub: str, parse: Callable[..., T]) -> dict[str, T]:
    out: dict[str, T] = {}
    directory = root / sub
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.json")):
        item = parse(_read(path), source=str(path.relative_to(root)))
        if item.id != path.stem:
            raise NnError(
                Exit.BAD_DATA,
                bi(
                    f"{path}: file name does not match id ({item.id})",
                    f"{path}: имя файла не совпадает с id ({item.id})",
                ),
            )
        if item.id in out:
            raise NnError(
                Exit.BAD_DATA, bi(f"{path}: duplicate id {item.id}", f"{path}: дубль id {item.id}")
            )
        out[item.id] = item
    return out


V = TypeVar("V")


def _merge(bundled: dict[str, V], personal: dict[str, V]) -> dict[str, V]:
    """Личное перекрывает поставляемое при совпадении ключа."""
    merged = dict(bundled)
    merged.update(personal)
    return merged


def _layer(bundled_root: Path, user_root: Path | None, sub: str, parse: Any) -> dict[str, Any]:
    bundled = _load_dir(bundled_root, sub, parse)
    if user_root is None or user_root == bundled_root:
        return bundled
    return _merge(bundled, _load_dir(user_root, sub, parse))


def load_catalog(root: Path | None = None, *, user_root: Path | None = None) -> Catalog:
    base = root or data_dir()
    personal = user_root if user_root is not None else (None if root else user_data_dir())

    caps_path = base / "capabilities.json"
    if not caps_path.is_file():
        raise NnError(Exit.BAD_DATA, bi(f"{caps_path} is missing", f"{caps_path} отсутствует"))
    caps, types = parse_capabilities(_read(caps_path))
    if personal is not None and (personal / "capabilities.json").is_file():
        extra_caps, extra_types = parse_capabilities(_read(personal / "capabilities.json"))
        caps = _merge(caps, extra_caps)
        types = _merge(types, extra_types)

    hosts = _layer(base, personal, "hosts", parse_host)
    if "local" not in hosts:
        raise NnError(
            Exit.BAD_DATA,
            bi(
                "hosts/local.json is missing: a local host is required",
                "hosts/local.json отсутствует: нужен хост local",
            ),
        )
    return Catalog(
        providers=_layer(base, personal, "providers", parse_provider),
        hosts=hosts,
        capabilities=caps,
        types=types,
        bridges=_layer(base, personal, "bridges", parse_bridge),
        recipes=_layer(base, personal, "recipes", parse_recipe),
        roles=_load_roles(base),
    )


def roles_path(base: Path) -> Path:
    """roles.json сначала ищется в стейте (его пишет nn adapt под эту машину),
    и только потом в репозитории как поставляемая заготовка."""
    from_state = state_dir() / "roles.json"
    return from_state if from_state.is_file() else base / "roles.json"


def _load_roles(base: Path) -> RolesConfig:
    path = roles_path(base)
    if not path.is_file():
        return RolesConfig()
    return parse_roles(_read(path), source=str(path))

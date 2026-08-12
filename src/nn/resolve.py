from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from nn.bridge import find_bridge
from nn.catalog import Catalog
from nn.detect import Runner, shell_runner
from nn.errors import Exit, NnError
from nn.i18n import bi
from nn.iotypes import accepts, output_type
from nn.model import Bridge, Host, Provider
from nn.registry import Registry
from nn.render import pick


@dataclass(frozen=True)
class Rejection:
    provider: str
    reason: str


@dataclass(frozen=True)
class Choice:
    provider: Provider
    host: Host
    bridge: Bridge | None
    manual: bool
    in_type: str | None
    out_type: str
    rejected: tuple[Rejection, ...]


def _recency(value: str) -> float:
    """Отрицательный epoch: свежий успех даёт меньшее число и выигрывает в min()."""
    if not value:
        return 0.0
    try:
        return -datetime.fromisoformat(value).timestamp()
    except ValueError:
        return 0.0


def _sort_key(
    provider: Provider, host: Host, last_success: Mapping[str, str]
) -> tuple[int, int, float, str]:
    local_first = 0 if host.kind == "local" else 1
    return (
        -provider.rank,
        local_first,
        _recency(last_success.get(provider.id, "")),
        provider.id,
    )


def resolve_role(
    role_name: str,
    *,
    catalog: Catalog,
    registry: Registry,
    exclude_vendors: frozenset[str] = frozenset(),
    exhausted: frozenset[str] = frozenset(),
    system: str | None = None,
) -> Choice:
    """Провайдер под роль по цепочке из roles.json.

    Цепочка объявлена человеком в roles.json, поэтому проход по ней — это не
    молчаливая подмена, а заранее выданное согласие. Исчерпанные окна и
    исключённые вендоры (ревью не должно идти тем же вендором, что писал патч)
    просто пропускаются, а причины сохраняются в rejected.
    """
    role = catalog.roles.roles.get(role_name)
    if role is None:
        known = ", ".join(sorted(catalog.roles.roles)) or "ни одной"
        raise NnError(Exit.NO_PROVIDER, f"роль {role_name} не описана (есть: {known})")

    rejected: list[Rejection] = []
    for provider_id in role.providers:
        provider = catalog.providers.get(provider_id)
        if provider is None:
            rejected.append(Rejection(provider_id, bi("no such manifest", "нет такого манифеста")))
            continue
        if provider.vendor_name in exclude_vendors:
            rejected.append(
                Rejection(
                    provider_id,
                    bi(
                        f"vendor {provider.vendor_name} is excluded",
                        f"вендор {provider.vendor_name} исключён",
                    ),
                )
            )
            continue
        if provider_id in exhausted:
            rejected.append(
                Rejection(provider_id, bi("quota window exhausted", "окно квоты исчерпано"))
            )
            continue
        host = catalog.hosts.get(provider.host)
        if host is None:
            rejected.append(
                Rejection(
                    provider_id,
                    bi(f"host {provider.host} is not described", f"хост {provider.host} не описан"),
                )
            )
            continue
        entry = registry.get(provider_id)
        if entry is None or entry.status != "ok":
            status = entry.status if entry else "нет в реестре"
            rejected.append(Rejection(provider_id, bi(f"status: {status}", f"статус: {status}")))
            continue
        if not provider.adapter and pick(provider.run, system=system) is None:
            rejected.append(
                Rejection(
                    provider_id, bi("no run template for this OS", "нет шаблона run под текущую ОС")
                )
            )
            continue
        return Choice(
            provider=provider,
            host=host,
            bridge=None,
            manual=(host.kind == "manual" or not host.auto),
            in_type="text",
            out_type="text",
            rejected=tuple(rejected),
        )

    summary = "; ".join(f"{r.provider}: {r.reason}" for r in rejected) or "цепочка пуста"
    raise NnError(Exit.NO_PROVIDER, f"под роль {role_name} никого не нашлось — {summary}")


def resolve(
    capability: str,
    *,
    catalog: Catalog,
    registry: Registry,
    in_type: str | None = None,
    pin: str | None = None,
    system: str | None = None,
    exhausted: frozenset[str] = frozenset(),
    allow_fallback: bool = False,
    last_success: Mapping[str, str] | None = None,
    runner: Runner = shell_runner,
) -> Choice:
    recent = last_success or {}
    rejected: list[Rejection] = []
    candidates: list[tuple[Provider, Host, Bridge | None]] = []
    quota_blocked: list[str] = []

    pool = [p for p in catalog.providers.values() if p.capability == capability]
    if pin:
        pool = [p for p in pool if p.id == pin]
        if not pool:
            raise NnError(
                Exit.NO_PROVIDER,
                f"провайдер {pin} не найден среди умеющих {capability}",
            )

    for provider in sorted(pool, key=lambda p: p.id):
        host = catalog.hosts.get(provider.host)
        if host is None:
            rejected.append(
                Rejection(
                    provider.id,
                    bi(f"host {provider.host} is not described", f"хост {provider.host} не описан"),
                )
            )
            continue
        entry = registry.get(provider.id)
        if entry is None:
            rejected.append(
                Rejection(
                    provider.id,
                    bi("absent from registry, run nn scan", "нет в реестре — сделай nn scan"),
                )
            )
            continue
        if entry.status != "ok":
            rejected.append(
                Rejection(
                    provider.id,
                    bi(
                        f"registry status: {entry.status} ({entry.reason})",
                        f"статус в реестре: {entry.status} ({entry.reason})",
                    ),
                )
            )
            continue
        if not provider.adapter and pick(provider.run, system=system) is None:
            rejected.append(
                Rejection(
                    provider.id, bi("no run template for this OS", "нет шаблона run под текущую ОС")
                )
            )
            continue
        bridge: Bridge | None = None
        if in_type is not None and not accepts(provider.io_in, in_type):
            bridge = find_bridge(in_type, provider.io_in, catalog.bridges, runner=runner)
            if bridge is None:
                rejected.append(
                    Rejection(
                        provider.id,
                        bi(
                            f"accepts {list(provider.io_in)}, input is {in_type}, no bridge",
                            f"принимает {list(provider.io_in)}, вход {in_type}, мостика нет",
                        ),
                    )
                )
                continue
        candidates.append((provider, host, bridge))

    if not candidates:
        summary = "; ".join(f"{r.provider}: {r.reason}" for r in rejected) or "кандидатов нет"
        if rejected and all("мостика нет" in r.reason for r in rejected):
            raise NnError(
                Exit.BAD_IO, f"{capability}: вход {in_type} никем не принимается — {summary}"
            )
        raise NnError(Exit.NO_PROVIDER, f"нет доступного провайдера для {capability} — {summary}")

    ranked = sorted(candidates, key=lambda item: _sort_key(item[0], item[1], recent))

    if exhausted:
        if allow_fallback:
            fresh = [item for item in ranked if item[0].id not in exhausted]
            for item in ranked:
                if item[0].id in exhausted:
                    quota_blocked.append(item[0].id)
                    rejected.append(
                        Rejection(
                            item[0].id,
                            bi(
                                "quota window exhausted, next one taken",
                                "окно квоты исчерпано, взят следующий",
                            ),
                        )
                    )
            if not fresh:
                raise NnError(
                    Exit.QUOTA,
                    f"все провайдеры {capability} исчерпали окно: {', '.join(quota_blocked)}",
                )
            ranked = fresh
        elif ranked[0][0].id in exhausted:
            spare = [item[0].id for item in ranked[1:] if item[0].id not in exhausted]
            hint = (
                f"живая альтернатива: {spare[0]}, повтори с --fallback" if spare else "замены нет"
            )
            raise NnError(
                Exit.QUOTA,
                f"{ranked[0][0].id} исчерпал окно квоты для {capability}. {hint}",
            )

    provider, host, bridge = ranked[0]
    cap = catalog.capabilities.get(capability)
    if cap is None:
        out_type = provider.io_out
    elif in_type is not None:
        out_type = output_type(cap, in_type)
    else:
        out_type = cap.out if cap.out != "same" else provider.io_out
    return Choice(
        provider=provider,
        host=host,
        bridge=bridge,
        manual=(host.kind == "manual" or not host.auto),
        in_type=in_type,
        out_type=out_type,
        rejected=tuple(rejected),
    )

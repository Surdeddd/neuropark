from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime

from nn.catalog import Catalog
from nn.detect import Runner, detect_over_runner, run_detect, shell_runner
from nn.i18n import bi
from nn.model import Host, Provider
from nn.paths import expand
from nn.registry import Entry, Registry, hostname
from nn.transport.ssh import runner_for


def _interpreter_of(provider: Provider) -> str | None:
    """Питон провайдера, если манифест закрепил свой в vars.py."""
    raw = provider.vars.get("py")
    return expand(raw) if raw else None


def _runs_elsewhere(host: Host) -> bool:
    """Хост, на котором nn действительно запускает команды сам, но не здесь.

    `auto: false` не считается: там команда только печатается, а проверять её
    исполнимость всё равно нечем — детект остаётся локальным, как и раньше.
    """
    return host.kind == "ssh" and host.auto


def _host_reachable(host: Host, runner: Runner) -> bool:
    if host.kind == "local":
        return True
    if not host.probe:
        return True
    code, _, _ = runner(host.probe, timeout=10)
    return code == 0


def scan(
    catalog: Catalog,
    *,
    runner: Runner = shell_runner,
    env: Mapping[str, str] | None = None,
    now: datetime | None = None,
    previous: Registry | None = None,
) -> Registry:
    moment = (now or datetime.now(UTC)).isoformat()
    reachable: dict[str, bool] = {}
    entries: dict[str, Entry] = {}

    for provider in catalog.providers.values():
        host = catalog.hosts.get(provider.host)
        if host is None:
            entries[provider.id] = Entry(
                provider.id,
                provider.host,
                "missing",
                bi(f"host {provider.host} is not described", f"хост {provider.host} не описан"),
            )
            continue

        if host.id not in reachable:
            reachable[host.id] = _host_reachable(host, runner)

        if not reachable[host.id]:
            old = previous.get(provider.id) if previous else None
            entries[provider.id] = Entry(
                provider.id,
                host.id,
                "stale",
                bi(
                    f"host {host.id} unreachable, data from the previous scan",
                    f"хост {host.id} недостижим, данные от прошлого скана",
                ),
                old.version if old else None,
                old.last_seen if old else None,
            )
            continue

        # Провайдер проверяется там, где он будет работать. Раньше детект всегда
        # шёл локально, и `nn ls` отвечал про эту машину вместо удалённой: бинарь
        # есть у меня — значит «ok», хотя запускать его собирались на gpu-box.
        if _runs_elsewhere(host):
            probe = runner_for(host, host.env)
            result = detect_over_runner(
                provider.detect,
                requires_key=provider.requires_key,
                env=host.env,
                runner=probe,
                interpreter=_interpreter_of(provider),
            )
        else:
            merged_env = dict(env if env is not None else os.environ)
            merged_env.update(host.env)
            probe = runner
            result = run_detect(
                provider.detect,
                requires_key=provider.requires_key,
                env=merged_env,
                runner=runner,
                interpreter=_interpreter_of(provider),
            )
        version: str | None = None
        if result.status == "ok" and provider.version_cmd:
            code, out, _ = probe(provider.version_cmd, timeout=20)
            if code == 0 and out.strip():
                version = out.strip().splitlines()[0][:60]
        entries[provider.id] = Entry(
            provider.id,
            host.id,
            result.status,
            result.reason,
            version,
            moment if result.status == "ok" else None,
        )

    return Registry(hostname=hostname(), generated_at=moment, entries=entries)

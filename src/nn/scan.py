from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime

from nn.catalog import Catalog
from nn.detect import Runner, run_detect, shell_runner
from nn.model import Host
from nn.registry import Entry, Registry, hostname


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
                provider.id, provider.host, "missing", f"хост {provider.host} не описан"
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
                f"хост {host.id} недостижим, данные от прошлого скана",
                old.version if old else None,
                old.last_seen if old else None,
            )
            continue

        merged_env = dict(env if env is not None else os.environ)
        merged_env.update(host.env)
        result = run_detect(
            provider.detect,
            requires_key=provider.requires_key,
            env=merged_env,
            runner=runner,
        )
        version: str | None = None
        if result.status == "ok" and provider.version_cmd:
            code, out, _ = runner(provider.version_cmd, timeout=20)
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

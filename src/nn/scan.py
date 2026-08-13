from __future__ import annotations

import os
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime

from nn.catalog import Catalog
from nn.detect import Runner, detect_over_runner, run_detect, shell_runner
from nn.errors import NnError
from nn.i18n import bi
from nn.model import Host, Provider
from nn.paths import expand
from nn.registry import Entry, Registry, hostname
from nn.transport.ssh import runner_for

# Детекты ждут внешних процессов и сети, а не считают, поэтому потоков берём
# больше числа ядер. Восемь — компромисс: заметный выигрыш и никакого шторма
# из подпроцессов на слабой машине.
WORKERS = 8


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


def _probe_provider(
    provider: Provider,
    host: Host,
    *,
    runner: Runner,
    env: Mapping[str, str] | None,
    moment: str,
) -> Entry:
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
    return Entry(
        provider.id,
        host.id,
        result.status,
        result.reason,
        version,
        moment if result.status == "ok" else None,
    )


def _safe_probe(
    provider: Provider,
    host: Host,
    *,
    runner: Runner,
    env: Mapping[str, str] | None,
    moment: str,
) -> Entry:
    """Один битый манифест не должен ослеплять весь парк.

    Раньше `NnError` из подстановки переменных (например, `vars.py` со ссылкой на
    несуществующую env-переменную) обрывал скан целиком, и человек оставался без
    реестра из-за одного файла.
    """
    try:
        return _probe_provider(provider, host, runner=runner, env=env, moment=moment)
    except NnError as exc:
        return Entry(provider.id, host.id, "missing", exc.message)


def _reachability(hosts: list[Host], runner: Runner, workers: int) -> dict[str, bool]:
    """Хосты опрашиваются разом: probe спящей машины упирается в свой таймаут."""
    if workers < 2 or len(hosts) < 2:
        return {host.id: _host_reachable(host, runner) for host in hosts}
    with ThreadPoolExecutor(max_workers=min(workers, len(hosts))) as pool:
        answers = pool.map(lambda host: (host.id, _host_reachable(host, runner)), hosts)
    return dict(answers)


def scan(
    catalog: Catalog,
    *,
    runner: Runner = shell_runner,
    env: Mapping[str, str] | None = None,
    now: datetime | None = None,
    previous: Registry | None = None,
    workers: int = WORKERS,
) -> Registry:
    moment = (now or datetime.now(UTC)).isoformat()
    entries: dict[str, Entry] = {}

    known: list[tuple[Provider, Host]] = []
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
        known.append((provider, host))

    needed = {host.id: host for _, host in known}
    reachable = _reachability(sorted(needed.values(), key=lambda h: h.id), runner, workers)

    pending: list[tuple[Provider, Host]] = []
    for provider, host in known:
        if reachable[host.id]:
            pending.append((provider, host))
            continue
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

    # Детекты независимы, а время тратят на ожидание: npm и brew по секунде,
    # http и ssh — на сеть, probe спящей машины — на свой таймаут. Замер на парке
    # с тремя недоступными хостами и четырьмя небыстрыми детектами: 10.6с → 3.6с.
    probed: dict[str, Entry] = {}
    if pending:
        limit = max(1, min(workers, len(pending)))
        if limit == 1:
            for provider, host in pending:
                probed[provider.id] = _safe_probe(
                    provider, host, runner=runner, env=env, moment=moment
                )
        else:
            with ThreadPoolExecutor(max_workers=limit) as pool:
                futures = {
                    pool.submit(
                        _safe_probe, provider, host, runner=runner, env=env, moment=moment
                    ): provider.id
                    for provider, host in pending
                }
                for future in as_completed(futures):
                    probed[futures[future]] = future.result()

    # Порядок реестра не должен зависеть от того, кто ответил первым.
    for provider, _ in known:
        if provider.id in probed:
            entries[provider.id] = probed[provider.id]

    return Registry(hostname=hostname(), generated_at=moment, entries=entries)

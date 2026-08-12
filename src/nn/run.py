from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from nn.catalog import Catalog
from nn.dossier import instructions_for
from nn.errors import Exit, NnError
from nn.i18n import bi
from nn.iotypes import ext_for
from nn.outcome import classify
from nn.paths import state_dir
from nn.render import build_context, pick, render
from nn.resolve import Choice
from nn.runlog import RunRecord, append
from nn.transport import Executed, LocalTransport, get_transport, resolve_env

NO_RETRY = {"quota", "refused", "empty"}
STDERR_TAIL_CHARS = 800
BRIDGE_TIMEOUT_S = 300


@dataclass(frozen=True)
class Envelope:
    status: str
    run_id: str
    provider: str
    capability: str
    host: str
    in_path: str | None
    out: str | None
    bridge: str | None
    ms: int
    exit_code: int
    outcome: str
    log: str
    patch: str | None = None
    command: str | None = None

    def to_json(self) -> str:
        payload = asdict(self)
        payload["in"] = payload.pop("in_path")
        return json.dumps(payload, ensure_ascii=False, indent=2)


def exit_code_for(env: Envelope) -> Exit:
    if env.status == "manual":
        return Exit.MANUAL
    return Exit.OK if env.outcome == "success" else Exit.PROVIDER_FAILED


def _out_dir() -> Path:
    path = state_dir() / "out"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _default_out(
    run_id: str,
    out_type: str,
    types: dict[str, tuple[str, ...]],
    out_ext: str | None = None,
) -> str:
    ext = out_ext or ext_for(out_type, types)
    return str(_out_dir() / f"{run_id}.{ext}")


def execute(
    choice: Choice,
    *,
    catalog: Catalog,
    in_path: str | None = None,
    out_path: str | None = None,
    extra: tuple[str, ...] = (),
    prompt: str | None = None,
    work_dir: str | None = None,
    retries: int = 1,
    now: datetime | None = None,
    with_dossier: bool = True,
) -> Envelope:
    provider = choice.provider
    if provider.adapter:
        raise NnError(
            Exit.BAD_DATA,
            bi(
                "adapter providers are not supported yet",
                "adapter-провайдеры пока не поддержаны",
            ),
        )

    moment = now or datetime.now(UTC)
    run_id = f"{int(moment.timestamp())}-{provider.id}"
    work = work_dir or str(Path.cwd())
    out_type = choice.out_type or provider.io_out
    final_out = out_path or _default_out(run_id, out_type, dict(catalog.types), provider.out_ext)
    log_file = _out_dir() / f"{run_id}.log"
    transport = get_transport(choice.host)
    env_vars = resolve_env(choice.host, {})
    tmp_prefix = str(_out_dir() / f"{run_id}-tmp")

    prompt_file: str | None = None
    if prompt is not None:
        body = prompt
        if with_dossier:
            advice = instructions_for(provider.id)
            if advice:
                preamble = bi(
                    "Mind the known gotchas of this tool:",
                    "Учти известные грабли этого инструмента:",
                )
                body = f"{preamble}\n{advice}\n\n{prompt}"
        prompt_file = str(_out_dir() / f"{run_id}-prompt.txt")
        Path(prompt_file).write_text(body, encoding="utf-8")

    source_path = in_path
    bridge_id: str | None = None
    log_parts: list[str] = []
    started = time.monotonic()

    if choice.bridge is not None and source_path is not None:
        bridge = choice.bridge
        bridge_out = f"{tmp_prefix}-bridge.{bridge.out_ext}"
        template = pick(bridge.run)
        if template is None:
            raise NnError(
                Exit.BAD_DATA,
                bi(
                    f"bridge {bridge.id}: no template for this OS",
                    f"мостик {bridge.id}: нет шаблона под текущую ОС",
                ),
            )
        command = render(template, {"in": source_path, "out": bridge_out, "tmp": tmp_prefix})
        # Мостик всегда локальный: его наличие проверяется локально (nn scan, doctor),
        # значит и запускать его надо здесь. Раньше он уходил в транспорт провайдера —
        # для ssh это была бы попытка запустить ffmpeg там, где его никто не проверял.
        result = LocalTransport().execute(
            command, host=choice.host, timeout_s=BRIDGE_TIMEOUT_S, work_dir=work, env=env_vars
        )
        log_parts.append(f"$ {command}\n{result.stdout}{result.stderr}")
        if result.exit_code != 0 and not choice.manual:
            log_file.write_text("\n".join(log_parts), encoding="utf-8")
            return _envelope(
                "error",
                run_id,
                choice,
                in_path,
                None,
                bridge.id,
                started,
                result,
                "crash",
                log_file,
            )
        bridge_id = bridge.id
        source_path = bridge_out

    context = build_context(
        provider,
        choice.host,
        in_path=source_path,
        out_path=final_out,
        tmp_prefix=tmp_prefix,
        work_dir=work,
        prompt_file=prompt_file,
        extra={f"extra{i}": value for i, value in enumerate(extra)},
    )

    # Транспорт получает право переписать пути под свою машину и забросить туда вход.
    # Провал подготовки — это исход прогона, а не исключение: недоступный хост должен
    # попасть в журнал, иначе досье не смогут на нём учиться.
    prepared = transport.prepare(context, host=choice.host, run_id=run_id, env=env_vars)
    if prepared.failure is not None:
        # Убрать надо и здесь: подготовка могла упасть уже после создания рабочей
        # директории на той стороне, и тогда она оставалась там навсегда.
        transport.finish()
        log_parts.append(f"$ {prepared.failure.command}\n{prepared.failure.stderr}")
        log_file.write_text("\n".join(log_parts), encoding="utf-8")
        return _envelope(
            "error",
            run_id,
            choice,
            in_path,
            None,
            bridge_id,
            started,
            prepared.failure,
            "timeout" if prepared.failure.timed_out else "crash",
            log_file,
        )
    context = prepared.context

    attempts = max(0, retries) + 1
    result = Executed(0, "", "", False, "")
    outcome = "crash"
    try:
        for attempt in range(attempts):
            for stage in ("pre", "run", "post"):
                template = pick(getattr(provider, stage))
                if template is None:
                    continue
                command = render(template, context)
                result = transport.execute(
                    command,
                    host=choice.host,
                    timeout_s=provider.timeout_s,
                    work_dir=work,
                    env=env_vars,
                )
                log_parts.append(f"$ {command}\n{result.stdout}{result.stderr}")
                if result.exit_code != 0 or result.timed_out:
                    break

            if choice.manual:
                log_file.write_text("\n".join(log_parts), encoding="utf-8")
                return _envelope(
                    "manual",
                    run_id,
                    choice,
                    in_path,
                    None,
                    bridge_id,
                    started,
                    result,
                    "manual",
                    log_file,
                )

            # Выход надо забрать до классификации: она смотрит на локальный файл,
            # а у удалённого прогона он пока лежит на той стороне.
            fetched = transport.collect()
            if fetched is not None:
                log_parts.append(f"$ {fetched.command}\n{fetched.stderr}")
                result = fetched

            outcome = classify(
                exit_code=result.exit_code,
                out_path=final_out,
                out_type=out_type,
                stderr=result.stderr,
                timed_out=result.timed_out,
                quota_patterns=provider.quota_patterns,
            )
            if outcome == "success" or outcome in NO_RETRY or attempt == attempts - 1:
                break
            log_parts.append(f"-- retry after outcome {outcome} --")
    finally:
        # Уборка обязана произойти, чем бы прогон ни кончился: иначе на удалённой
        # машине копятся директории прогонов, и никто их никогда не удалит.
        transport.finish()

    log_file.write_text("\n".join(log_parts), encoding="utf-8")
    status = "ok" if outcome == "success" else "error"
    return _envelope(
        status,
        run_id,
        choice,
        in_path,
        final_out if outcome == "success" else None,
        bridge_id,
        started,
        result,
        outcome,
        log_file,
    )


def _envelope(
    status: str,
    run_id: str,
    choice: Choice,
    in_path: str | None,
    out: str | None,
    bridge_id: str | None,
    started: float,
    result: Executed,
    outcome: str,
    log_file: Path,
) -> Envelope:
    env = Envelope(
        status=status,
        run_id=run_id,
        provider=choice.provider.id,
        capability=choice.provider.capability,
        host=choice.host.id,
        in_path=in_path,
        out=out,
        bridge=bridge_id,
        ms=int((time.monotonic() - started) * 1000),
        exit_code=result.exit_code,
        outcome=outcome,
        log=str(log_file),
        command=result.command or None,
    )
    if outcome == "manual":
        return env
    append(
        RunRecord(
            ts=datetime.now(UTC).isoformat(),
            run_id=env.run_id,
            provider=env.provider,
            capability=env.capability,
            host=env.host,
            in_type=choice.in_type,
            out=env.out,
            exit_code=env.exit_code,
            outcome=env.outcome,
            ms=env.ms,
            stderr_tail=result.stderr[-STDERR_TAIL_CHARS:],
        )
    )
    return env

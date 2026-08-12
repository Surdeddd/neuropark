from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from nn.catalog import Catalog, load_catalog
from nn.dossier import learn, pending_count, should_auto_learn
from nn.drift import compare, format_drift
from nn.errors import Exit, NnError
from nn.i18n import bi
from nn.iotypes import check_extra, type_of
from nn.paths import state_dir
from nn.quota import compute, exhausted_set
from nn.registry import Registry, is_expired, load, save
from nn.report import (
    BURN_HEADERS,
    DOCTOR_HEADERS,
    LS_HEADERS,
    QUOTA_HEADERS,
    RECIPE_HEADERS,
    ROLE_HEADERS,
    STATS_HEADERS,
    WHY_HEADERS,
    ls_rows,
    stats_rows,
    table,
    why_rows,
)
from nn.resolve import QUOTA_BLOCKED, resolve
from nn.run import execute, exit_code_for
from nn.runlog import last_success_map, read_all
from nn.scan import scan

VERSION = "0.6.0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nn",
        description=bi("Neural park catalog", "каталог парка нейронок"),
    )
    parser.add_argument("--version", action="version", version=f"nn {VERSION}")
    parser.add_argument(
        "--json", action="store_true", help=bi("machine-readable output", "машинный вывод")
    )
    subs = parser.add_subparsers(dest="command")

    subs.add_parser(
        "scan", help=bi("probe detectors, write registry", "обойти детекты, записать реестр")
    )

    ls_cmd = subs.add_parser("ls", help=bi("show the park", "показать парк"))
    ls_cmd.add_argument("capability", nargs="?")

    why_cmd = subs.add_parser(
        "why", help=bi("explain provider choice", "объяснить выбор провайдера")
    )
    why_cmd.add_argument("capability")
    why_cmd.add_argument("--in-type", dest="in_type")

    run_cmd = subs.add_parser("run", help=bi("run a capability", "запустить capability"))
    run_cmd.add_argument("capability")
    run_cmd.add_argument("input", nargs="?")
    run_cmd.add_argument("-o", "--out")
    run_cmd.add_argument("--provider")
    run_cmd.add_argument("--extra", action="append", default=[])
    run_cmd.add_argument("--prompt")
    run_cmd.add_argument("--retries", type=int, default=1)
    run_cmd.add_argument(
        "--fallback",
        action="store_true",
        help=bi(
            "allow the next provider when the best one is quota-exhausted",
            "разрешить следующего провайдера, если у лучшего исчерпано окно",
        ),
    )
    run_cmd.add_argument(
        "--no-dossier",
        action="store_true",
        help=bi(
            "do not inject learned lessons into the prompt",
            "не подмешивать накопленные уроки в промпт",
        ),
    )

    subs.add_parser("quota", help=bi("quota windows", "окна квот: сожжено, что простаивает"))
    subs.add_parser("learn", help=bi("distil run outcomes into dossiers", "сжать исходы в досье"))

    burn_cmd = subs.add_parser("burn", help=bi("burn idle quota", "прожечь простаивающую квоту"))
    burn_subs = burn_cmd.add_subparsers(dest="burn_command")
    burn_add = burn_subs.add_parser("add", help=bi("queue a task", "положить задачу в очередь"))
    burn_add.add_argument("capability")
    burn_add.add_argument("input")
    burn_add.add_argument("--note", default="")
    burn_run = burn_subs.add_parser(
        "run", help=bi("show or execute matching tasks", "показать или выполнить задачи")
    )
    burn_run.add_argument(
        "--yes", action="store_true", help=bi("actually execute", "действительно запускать")
    )

    recipe_cmd = subs.add_parser("recipe", help=bi("ready-made chains", "готовые цепочки"))
    recipe_subs = recipe_cmd.add_subparsers(dest="recipe_command")
    recipe_subs.add_parser("ls", help=bi("list recipes", "список рецептов"))
    recipe_run = recipe_subs.add_parser("run", help=bi("execute a recipe", "выполнить рецепт"))
    recipe_run.add_argument("recipe_id")
    recipe_run.add_argument("input")

    init_cmd = subs.add_parser(
        "init",
        help=bi(
            "detect installed tools and write manifests",
            "найти установленные инструменты и записать манифесты",
        ),
    )
    init_cmd.add_argument(
        "--dry-run",
        action="store_true",
        help=bi("only show what would be written", "только показать, что было бы записано"),
    )

    subs.add_parser("adapt", help=bi("build roles.json for this machine", "собрать roles.json"))

    orch = subs.add_parser(
        "orchestrate", help=bi("drive a task through role stages", "провести задачу по стадиям")
    )
    orch.add_argument("task")
    orch.add_argument(
        "--dir", default=".", help=bi("repository to work in", "репозиторий, в котором работать")
    )
    orch.add_argument("--pattern", default="default")
    orch.add_argument(
        "--role", default="mechanics", help=bi("role for the work stage", "роль стадии work")
    )
    orch.add_argument("--fanout", type=int, default=1)

    subs.add_parser("doctor", help=bi("check catalog integrity", "проверить целостность каталога"))
    subs.add_parser("stats", help=bi("what actually gets used", "сколько раз что вызывалось"))
    return parser


def _exhausted(catalog: Catalog) -> frozenset[str]:
    """Провайдеры с исчерпанным окном, посчитанные из runs.jsonl.

    Само решение, что с ними делать, принимает резолвер: без --fallback он
    отказывается и называет альтернативу, с флагом — переключается явно.
    """
    now = datetime.now(UTC)
    return exhausted_set(compute(catalog.providers, read_all(), now=now), now=now)


def _auto_learn() -> None:
    """Досье пополняются сами после любой команды, которая что-то запускала."""
    if should_auto_learn():
        touched = learn()
        if touched:
            label = bi("dossiers updated", "досье обновлены")
            print(f"{label}: {', '.join(touched)}", file=sys.stderr)


def _require_files(paths: tuple[str, ...], *, what: str) -> None:
    for raw in paths:
        if not Path(raw).expanduser().is_file():
            raise NnError(Exit.BAD_IO, bi(f"{what} {raw} not found", f"{what} {raw} не найден"))


def _load_registry() -> Registry:
    registry = load()
    if is_expired(registry, now=datetime.now(UTC)):
        raise NnError(
            Exit.REGISTRY_STALE,
            bi(
                f"registry from {registry.generated_at[:10]} is older than 30 days, run nn scan",
                f"реестр от {registry.generated_at[:10]} старше 30 дней — сделай nn scan",
            ),
        )
    return registry


def _cmd_scan(as_json: bool) -> int:
    catalog = load_catalog()
    previous: Registry | None
    try:
        previous = load()
    except NnError:
        previous = None
    registry = scan(catalog, previous=previous)
    path = save(registry)
    drift = compare(previous, registry)
    counts: dict[str, int] = {}
    for entry in registry.entries.values():
        counts[entry.status] = counts.get(entry.status, 0) + 1
    if as_json:
        print(
            json.dumps(
                {
                    "registry": str(path),
                    "counts": counts,
                    "drift": [asdict(item) for item in drift],
                },
                ensure_ascii=False,
            )
        )
    else:
        summary = ", ".join(f"{status}: {count}" for status, count in sorted(counts.items()))
        empty = bi("no providers", "провайдеров нет")
        label = bi("registry written", "реестр записан")
        print(f"{label}: {path}\n{summary or empty}")
        if drift:
            title = bi("changes since last scan", "изменения с прошлого скана")
            print(f"\n{title}:\n{format_drift(drift)}")
    return int(Exit.OK)


def _cmd_ls(capability: str | None, as_json: bool) -> int:
    catalog = load_catalog()
    registry = _load_registry()
    if as_json:
        print(
            json.dumps(
                {
                    "hostname": registry.hostname,
                    "generated_at": registry.generated_at,
                    "entries": {k: asdict(v) for k, v in registry.entries.items()},
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(table(ls_rows(catalog, registry, capability=capability), LS_HEADERS))
    return int(Exit.OK)


def _cmd_why(capability: str, in_type: str | None, as_json: bool) -> int:
    catalog = load_catalog()
    registry = _load_registry()
    choice = resolve(
        capability,
        catalog=catalog,
        registry=registry,
        in_type=in_type,
        exhausted=_exhausted(catalog),
        allow_fallback=True,
        last_success=last_success_map(),
    )
    if as_json:
        print(
            json.dumps(
                {
                    "chosen": choice.provider.id,
                    "host": choice.host.id,
                    "bridge": choice.bridge.id if choice.bridge else None,
                    "manual": choice.manual,
                    "out_type": choice.out_type,
                    "rejected": [asdict(r) for r in choice.rejected],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(table(why_rows(choice), WHY_HEADERS))
        if any(r.code == QUOTA_BLOCKED for r in choice.rejected):
            print(
                "\nу кого-то исчерпано окно квоты: nn run откажется кодом 6,"
                " пока не передашь --fallback"
            )
    return int(Exit.OK)


def _cmd_run(args: argparse.Namespace) -> int:
    catalog = load_catalog()
    registry = _load_registry()
    in_type: str | None = None
    if args.input:
        source = Path(args.input)
        if not source.is_file():
            raise NnError(
                Exit.BAD_IO,
                bi(f"input file {source} not found", f"входной файл {source} не найден"),
            )
        in_type = type_of(str(source), catalog.types)
    _require_files(tuple(args.extra), what="дополнительный вход")
    cap = catalog.capabilities.get(args.capability)
    if cap is not None:
        check_extra(cap, tuple(args.extra), catalog.types)
    choice = resolve(
        args.capability,
        catalog=catalog,
        registry=registry,
        in_type=in_type,
        pin=args.provider,
        exhausted=_exhausted(catalog),
        allow_fallback=args.fallback,
        last_success=last_success_map(),
    )
    envelope = execute(
        choice,
        catalog=catalog,
        in_path=args.input,
        out_path=args.out,
        extra=tuple(args.extra),
        prompt=args.prompt,
        retries=args.retries,
        with_dossier=not args.no_dossier,
    )
    print(envelope.to_json())
    if envelope.status == "manual":
        label = bi("run this manually", "выполни вручную")
        print(f"\n{label}:\n{envelope.command}", file=sys.stderr)
    _auto_learn()
    return int(exit_code_for(envelope))


def _cmd_init(args: argparse.Namespace) -> int:
    from nn.init import discover, ensure_local_host, write_manifests

    candidates = discover()
    rows = [
        [
            item.id,
            item.capability,
            bi("found", "найден") if item.found else bi("absent", "нет"),
            (item.model or "-") if item.found else item.reason,
        ]
        for item in candidates
    ]
    headers = [
        bi("tool", "инструмент"),
        "capability",
        bi("state", "состояние"),
        bi("model / reason", "модель / причина"),
    ]
    if args.json:
        payload = [
            {
                "id": item.id,
                "capability": item.capability,
                "found": item.found,
                "reason": item.reason,
                "model": item.model,
                "needs_editing": item.needs_editing,
            }
            for item in candidates
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return int(Exit.OK)

    print(table(rows, headers))
    found = [item for item in candidates if item.found]
    if not found:
        print(
            bi(
                "\nnothing detected. Install a tool or write a manifest by hand:"
                " see examples/providers",
                "\nничего не найдено. Поставь инструмент либо напиши манифест руками:"
                " смотри examples/providers",
            )
        )
        return int(Exit.OK)

    if args.dry_run:
        names = ", ".join(item.id for item in found)
        print(bi(f"\nwould write: {names}", f"\nбыли бы записаны: {names}"))
        return int(Exit.OK)

    host = ensure_local_host()
    written = write_manifests(found)
    print(bi(f"\nwritten manifests: {len(written)}", f"\nзаписано манифестов: {len(written)}"))
    print(f"  {written[0].parent}" if written else f"  {host.parent}")
    needs = [item.id for item in found if item.needs_editing]
    if needs:
        print(
            bi(
                f"needs your editing before use: {', '.join(needs)}",
                f"требуют правки перед использованием: {', '.join(needs)}",
            )
        )
    print(bi("next: nn scan && nn ls", "дальше: nn scan && nn ls"))
    return int(Exit.OK)


def _cmd_adapt(as_json: bool) -> int:
    from nn.adapt import build, write

    catalog = load_catalog()
    registry = _load_registry()
    result = build(catalog, registry)
    path = write(result)
    if as_json:
        print(
            json.dumps(
                {"roles": str(path), "config": result.to_payload()}, ensure_ascii=False, indent=2
            )
        )
        return int(Exit.OK)
    rows = [
        [name, ", ".join(plan.providers), "да" if plan.worktree else "нет"]
        for name, plan in sorted(result.roles.items())
    ]
    print(table(rows, ROLE_HEADERS))
    print(f"\n{bi('written', 'записано')}: {path}")
    print(
        "edit the order by hand if wrong: it is the fallback chain"
        " / поправь порядок руками, это цепочка фолбэков"
    )
    return int(Exit.OK)


def _cmd_orchestrate(args: argparse.Namespace) -> int:
    from nn.orchestrate import orchestrate, save_report

    catalog = load_catalog()
    registry = _load_registry()
    repo = Path(args.dir).expanduser().resolve()
    results = orchestrate(
        args.task,
        catalog=catalog,
        registry=registry,
        repo=repo,
        pattern=args.pattern,
        work_role=args.role,
        fanout=args.fanout,
        exhausted=_exhausted(catalog),
    )
    run_id = results[0].envelope.run_id if results else "empty"
    path = save_report(results, run_id)
    patches = [item.patch for item in results if item.patch]
    print(f"{bi('report', 'отчёт')}: {path}")
    for patch in patches:
        label = bi("patch", "патч")
        note = bi("NOT applied, merge is yours", "НЕ применён, мерж твой")
        print(f"{label}: {patch} ({note})")
    failed = [item for item in results if item.envelope.outcome != "success"]
    if failed:
        names = ", ".join(f"{i.stage}/{i.provider}: {i.envelope.outcome}" for i in failed)
        label = bi("failed stages", "неудачные стадии")
        print(f"{label}: {names}", file=sys.stderr)
        return int(Exit.PROVIDER_FAILED)
    return int(Exit.OK)


def _cmd_learn(as_json: bool) -> int:
    pending = pending_count()
    touched = learn()
    if as_json:
        print(json.dumps({"providers": touched, "processed": pending}, ensure_ascii=False))
        return int(Exit.OK)
    if not touched and not pending:
        print(bi("nothing new", "новых исходов нет"))
    elif not touched:
        print(
            bi(
                f"processed {pending} new records, no lessons yet;"
                " thresholds: 3 repeats of one error signature, 3 empty answers, 2 timeouts",
                f"обработано новых записей: {pending}, уроков не набралось;"
                " пороги: 3 повтора одной подписи ошибки, 3 пустых ответа, 2 таймаута",
            )
        )
    else:
        label = bi("dossiers updated", "досье обновлены")
        print(f"{label}: {', '.join(touched)}")
        for provider in touched:
            print(f"  {state_dir() / 'dossiers' / f'{provider}.md'}")
    return int(Exit.OK)


def _cmd_quota(as_json: bool) -> int:
    catalog = load_catalog()
    now = datetime.now(UTC)
    windows = compute(catalog.providers, read_all(), now=now)
    if as_json:
        payload = {
            pid: {
                "window_h": w.window_h,
                "calls": w.calls,
                "soft_cap": w.soft_cap,
                "remaining": w.remaining,
                "resets_at": w.resets_at.isoformat() if w.resets_at else None,
                "exhausted": w.is_exhausted(now=now),
            }
            for pid, w in windows.items()
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return int(Exit.OK)
    rows = [
        [
            pid,
            f"{w.window_h:g}ч",
            f"{w.calls}/{w.soft_cap}" if w.soft_cap else str(w.calls),
            "исчерпано" if w.is_exhausted(now=now) else ("простаивает" if w.idle else "живое"),
            w.resets_at.strftime("%H:%M") if w.resets_at else "-",
        ]
        for pid, w in sorted(windows.items())
    ]
    print(table(rows, QUOTA_HEADERS))
    if not windows:
        print(bi("\nno manifest declares window_h", "ни один манифест не объявил window_h"))
    return int(Exit.OK)


def _cmd_burn(args: argparse.Namespace) -> int:
    from nn.burn import BurnTask, candidates, enqueue, read_queue, rewrite_queue

    catalog = load_catalog()
    now = datetime.now(UTC)

    if args.burn_command == "add":
        enqueue(
            BurnTask(
                ts=now.isoformat(),
                capability=args.capability,
                input=str(Path(args.input).expanduser()),
                note=args.note,
            )
        )
        label = bi("queued", "в очередь")
        print(f"{label}: {args.capability} ← {args.input}")
        return int(Exit.OK)

    windows = compute(catalog.providers, read_all(), now=now)
    tasks = read_queue()
    provider_capability = {pid: p.capability for pid, p in catalog.providers.items()}
    pairs = candidates(windows, tasks, provider_capability, now=now)

    if not pairs:
        print(
            bi(
                "nothing to burn: no idle windows or the queue is empty",
                "прожигать нечего: нет простаивающих окон либо очередь пуста",
            )
        )
        return int(Exit.OK)

    rows = [
        [w.provider, t.capability, t.input, w.resets_at.strftime("%H:%M") if w.resets_at else "-"]
        for w, t in pairs
    ]
    print(table(rows, BURN_HEADERS))

    if not args.yes:
        print(bi("\nthis is a proposal, add --yes to run", "запуск с --yes"))
        return int(Exit.OK)

    registry = _load_registry()
    exhausted = exhausted_set(windows, now=now)
    done: list[str] = []
    for window, item in pairs:
        if window.provider in exhausted:
            reason = bi("window closed, skipping", "окно закрылось, пропускаю")
            print(f"{window.provider}: {reason}", file=sys.stderr)
            continue
        if not Path(item.input).expanduser().is_file():
            gone = bi("is gone, task dropped from queue", "исчез, задача выброшена из очереди")
            print(f"{item.input} {gone}", file=sys.stderr)
            done.append(item.input)
            continue
        choice = resolve(
            item.capability,
            catalog=catalog,
            registry=registry,
            in_type=type_of(item.input, catalog.types),
            pin=window.provider,
            exhausted=exhausted,
            last_success=last_success_map(),
        )
        envelope = execute(choice, catalog=catalog, in_path=item.input)
        print(envelope.to_json())
        if envelope.outcome == "success":
            done.append(item.input)
    rewrite_queue([t for t in tasks if t.input not in done])
    _auto_learn()
    return int(Exit.OK)


def _cmd_recipe(args: argparse.Namespace) -> int:
    from nn.recipe import run_recipe

    catalog = load_catalog()
    if args.recipe_command == "ls":
        rows = [
            [
                r.id,
                r.description[:60],
                " → ".join(s.capability or f"role:{s.role}" for s in r.steps),
            ]
            for r in sorted(catalog.recipes.values(), key=lambda r: r.id)
        ]
        print(table(rows, RECIPE_HEADERS))
        return int(Exit.OK)

    registry = _load_registry()
    recipe = catalog.recipes.get(args.recipe_id)
    if recipe is None:
        known = ", ".join(sorted(catalog.recipes)) or "ни одного"
        raise NnError(
            Exit.BAD_DATA,
            bi(
                f"recipe {args.recipe_id} does not exist (available: {known})",
                f"рецепта {args.recipe_id} нет (есть: {known})",
            ),
        )
    source = Path(args.input)
    if not source.is_file():
        raise NnError(
            Exit.BAD_IO,
            bi(f"input file {source} not found", f"входной файл {source} не найден"),
        )

    results = run_recipe(
        recipe,
        catalog=catalog,
        registry=registry,
        input_path=str(source),
        exhausted=_exhausted(catalog),
    )
    _auto_learn()
    payload = [json.loads(r.envelope.to_json()) for r in results]
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not results:
        return int(Exit.BAD_DATA)
    last = results[-1].envelope
    if all(r.envelope.outcome == "success" for r in results):
        return int(Exit.OK)
    return int(exit_code_for(last))


def _cmd_doctor(as_json: bool) -> int:
    from nn.doctor import check

    catalog = load_catalog()
    registry: Registry | None
    try:
        registry = _load_registry()
    except NnError:
        registry = None
    findings = check(catalog, registry)
    if as_json:
        print(json.dumps([asdict(f) for f in findings], ensure_ascii=False, indent=2))
    else:
        rows = [[f.severity, f.subject, f.message] for f in findings]
        print(table(rows, DOCTOR_HEADERS))
    return int(Exit.BAD_DATA) if any(f.severity == "error" for f in findings) else int(Exit.OK)


def _cmd_stats(as_json: bool) -> int:
    runs = read_all()
    if as_json:
        print(json.dumps(stats_rows(runs), ensure_ascii=False))
    else:
        print(table(stats_rows(runs), STATS_HEADERS))
    return int(Exit.OK)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "scan":
            return _cmd_scan(args.json)
        if args.command == "ls":
            return _cmd_ls(args.capability, args.json)
        if args.command == "why":
            return _cmd_why(args.capability, args.in_type, args.json)
        if args.command == "run":
            return _cmd_run(args)
        if args.command == "quota":
            return _cmd_quota(args.json)
        if args.command == "learn":
            return _cmd_learn(args.json)
        if args.command == "init":
            return _cmd_init(args)
        if args.command == "adapt":
            return _cmd_adapt(args.json)
        if args.command == "orchestrate":
            return _cmd_orchestrate(args)
        if args.command == "burn":
            return _cmd_burn(args)
        if args.command == "recipe":
            return _cmd_recipe(args)
        if args.command == "doctor":
            return _cmd_doctor(args.json)
        if args.command == "stats":
            return _cmd_stats(args.json)
        parser.print_help()
        return int(Exit.OK)
    except NnError as exc:
        print(f"nn: {exc.message}", file=sys.stderr)
        return int(exc.code)


if __name__ == "__main__":
    sys.exit(main())

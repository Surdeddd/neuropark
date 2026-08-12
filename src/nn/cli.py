from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from nn.catalog import load_catalog
from nn.errors import Exit, NnError
from nn.iotypes import check_extra, type_of
from nn.registry import Registry, is_expired, load, save
from nn.report import LS_HEADERS, STATS_HEADERS, WHY_HEADERS, ls_rows, stats_rows, table, why_rows
from nn.resolve import resolve
from nn.run import execute, exit_code_for
from nn.runlog import last_success_map, read_all
from nn.scan import scan

VERSION = "0.1.0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nn", description="каталог парка нейронок")
    parser.add_argument("--version", action="version", version=f"nn {VERSION}")
    parser.add_argument("--json", action="store_true", help="машинный вывод")
    subs = parser.add_subparsers(dest="command")

    subs.add_parser("scan", help="обойти детекты и записать реестр")

    ls_cmd = subs.add_parser("ls", help="показать парк")
    ls_cmd.add_argument("capability", nargs="?")

    why_cmd = subs.add_parser("why", help="объяснить выбор провайдера")
    why_cmd.add_argument("capability")
    why_cmd.add_argument("--in-type", dest="in_type")

    run_cmd = subs.add_parser("run", help="запустить capability")
    run_cmd.add_argument("capability")
    run_cmd.add_argument("input", nargs="?")
    run_cmd.add_argument("-o", "--out")
    run_cmd.add_argument("--provider")
    run_cmd.add_argument("--extra", action="append", default=[])
    run_cmd.add_argument("--prompt")
    run_cmd.add_argument("--retries", type=int, default=1)

    recipe_cmd = subs.add_parser("recipe", help="готовые цепочки")
    recipe_subs = recipe_cmd.add_subparsers(dest="recipe_command")
    recipe_subs.add_parser("ls", help="список рецептов")
    recipe_run = recipe_subs.add_parser("run", help="выполнить рецепт")
    recipe_run.add_argument("recipe_id")
    recipe_run.add_argument("input")

    subs.add_parser("doctor", help="проверить целостность каталога")
    subs.add_parser("stats", help="сколько раз что вызывалось")
    return parser


def _load_registry() -> Registry:
    registry = load()
    if is_expired(registry, now=datetime.now(UTC)):
        raise NnError(
            Exit.REGISTRY_STALE,
            f"реестр от {registry.generated_at[:10]} старше 30 дней — сделай nn scan",
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
    counts: dict[str, int] = {}
    for entry in registry.entries.values():
        counts[entry.status] = counts.get(entry.status, 0) + 1
    if as_json:
        print(json.dumps({"registry": str(path), "counts": counts}, ensure_ascii=False))
    else:
        summary = ", ".join(f"{status}: {count}" for status, count in sorted(counts.items()))
        print(f"реестр записан: {path}\n{summary or 'провайдеров нет'}")
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
    return int(Exit.OK)


def _cmd_run(args: argparse.Namespace) -> int:
    catalog = load_catalog()
    registry = _load_registry()
    in_type: str | None = None
    if args.input:
        source = Path(args.input)
        if not source.is_file():
            raise NnError(Exit.BAD_IO, f"входной файл {source} не найден")
        in_type = type_of(str(source), catalog.types)
    cap = catalog.capabilities.get(args.capability)
    if cap is not None:
        check_extra(cap, tuple(args.extra), catalog.types)
    choice = resolve(
        args.capability,
        catalog=catalog,
        registry=registry,
        in_type=in_type,
        pin=args.provider,
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
    )
    print(envelope.to_json())
    if envelope.status == "manual":
        print(f"\nвыполни вручную:\n{envelope.command}", file=sys.stderr)
    return int(exit_code_for(envelope))


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
        print(table(rows, ["рецепт", "описание", "шаги"]))
        return int(Exit.OK)

    registry = _load_registry()
    recipe = catalog.recipes.get(args.recipe_id)
    if recipe is None:
        known = ", ".join(sorted(catalog.recipes)) or "ни одного"
        raise NnError(Exit.BAD_DATA, f"рецепта {args.recipe_id} нет (есть: {known})")
    source = Path(args.input)
    if not source.is_file():
        raise NnError(Exit.BAD_IO, f"входной файл {source} не найден")

    results = run_recipe(recipe, catalog=catalog, registry=registry, input_path=str(source))
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
        from nn.report import DOCTOR_HEADERS

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

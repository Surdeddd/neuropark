from __future__ import annotations

from typing import Any

from nn.errors import Exit, NnError
from nn.i18n import bi
from nn.model import Bridge, Capability, Host, Provider, Recipe, Role, RolesConfig, Step

KINDS = {"model", "tool", "agent"}
STAGES = {"spec", "work", "cross-review", "verdict"}
HOST_KINDS = {"local", "ssh", "http", "manual"}
OS_KEYS = {"", "darwin", "linux", "win"}


def _bad(source: str, what: str) -> NnError:
    return NnError(
        Exit.BAD_DATA,
        bi(
            f"{source}: invalid field {what}",
            f"{source}: некорректное поле {what}",
        ),
    )


def _templates(raw: Any, source: str, field: str) -> dict[str, str]:
    if raw is None:
        return {}
    if isinstance(raw, str):
        return {"": raw}
    if isinstance(raw, dict):
        unknown = set(raw) - OS_KEYS
        if unknown:
            raise _bad(
                source, f"{field} ({bi('unknown OS keys', 'неизвестные ОС')}: {sorted(unknown)})"
            )
        return {str(k): str(v) for k, v in raw.items()}
    raise _bad(source, field)


def bilingual(raw: Any, source: str, field: str) -> str:
    """Текст для человека из файла данных: либо {"en": ..., "ru": ...}, либо одна строка.

    Одна строка допустима только для языконезависимого текста. Склейка двух языков
    в один литерал — это тот же баг, что и в коде: переключение языка её не берёт.
    """
    if isinstance(raw, dict):
        english = str(raw.get("en") or "")
        russian = str(raw.get("ru") or "")
        if not english or not russian:
            label = bi(
                "the bilingual form needs both keys: en and ru",
                "в двуязычной форме нужны оба ключа: en и ru",
            )
            raise _bad(source, f"{field} ({label})")
        return bi(english, russian)
    return str(raw or "")


def _notes(raw: Any, source: str) -> str:
    text = bilingual(raw, source, "notes")
    if not text:
        label = bi("required: speed, quality, gotchas", "обязательны: скорость, качество, грабли")
        raise _bad(source, f"notes ({label})")
    return text


def parse_provider(raw: dict[str, Any], source: str) -> Provider:
    pid = str(raw.get("id") or "")
    if not pid:
        raise _bad(source, "id")
    if not raw.get("capability"):
        raise _bad(source, "capability")
    kind = str(raw.get("kind") or "")
    if kind not in KINDS:
        raise _bad(source, f"kind ({bi('expected one of', 'ожидалось одно из')} {sorted(KINDS)})")
    detect = raw.get("detect")
    if not isinstance(detect, dict) or not detect:
        raise _bad(
            source,
            bi(
                "detect (required, and it cannot be empty)",
                "detect (обязателен и не может быть пустым)",
            ),
        )
    io = raw.get("io")
    if not isinstance(io, dict):
        raise _bad(source, "io")
    io_in = tuple(str(x) for x in io.get("in") or ())
    if not io_in:
        raise _bad(source, "io.in")
    if not io.get("out"):
        raise _bad(source, "io.out")
    run = _templates(raw.get("run"), source, "run")
    adapter = raw.get("adapter")
    if run and adapter:
        raise _bad(
            source, bi("adapter (mutually exclusive with run)", "adapter (взаимоисключающ с run)")
        )
    if not run and not adapter:
        raise _bad(
            source, bi("run (required unless adapter is set)", "run (обязателен, если нет adapter)")
        )
    notes = _notes(raw.get("notes"), source)
    return Provider(
        id=pid,
        capability=str(raw["capability"]),
        kind=kind,
        detect=dict(detect),
        io_in=io_in,
        io_out=str(io["out"]),
        notes=notes,
        source=source,
        out_ext=str(io["out_ext"]).lstrip(".") if io.get("out_ext") else None,
        host=str(raw.get("host") or "local"),
        rank=int(raw.get("rank") or 0),
        version_cmd=raw.get("version_cmd"),
        vars={str(k): str(v) for k, v in (raw.get("vars") or {}).items()},
        pre=_templates(raw.get("pre"), source, "pre"),
        run=run,
        post=_templates(raw.get("post"), source, "post"),
        adapter=adapter,
        timeout_s=int(raw.get("timeout_s") or 900),
        window_h=float(raw["window_h"]) if raw.get("window_h") else None,
        soft_cap_calls=int(raw["soft_cap_calls"]) if raw.get("soft_cap_calls") else None,
        quota_patterns=tuple(str(x) for x in raw.get("quota_patterns") or ()),
        requires_key=tuple(str(x) for x in raw.get("requires_key") or ()),
        roles=tuple(str(x) for x in raw.get("roles") or ()),
        vendor=str(raw["vendor"]) if raw.get("vendor") else None,
    )


def parse_host(raw: dict[str, Any], source: str) -> Host:
    hid = str(raw.get("id") or "")
    if not hid:
        raise _bad(source, "id")
    kind = str(raw.get("kind") or "")
    if kind not in HOST_KINDS:
        raise _bad(
            source, f"kind ({bi('expected one of', 'ожидалось одно из')} {sorted(HOST_KINDS)})"
        )
    if kind == "ssh" and not raw.get("addr"):
        raise _bad(source, bi("addr (required for kind=ssh)", "addr (обязателен для kind=ssh)"))
    return Host(
        id=hid,
        kind=kind,
        addr=raw.get("addr"),
        os=raw.get("os"),
        auto=bool(raw.get("auto", True)),
        probe=raw.get("probe"),
        paths={str(k): str(v) for k, v in (raw.get("paths") or {}).items()},
        env={str(k): str(v) for k, v in (raw.get("env") or {}).items()},
        notes=bilingual(raw.get("notes"), source, "notes"),
    )


def parse_capabilities(
    raw: dict[str, Any],
) -> tuple[dict[str, Capability], dict[str, tuple[str, ...]]]:
    types = {
        str(name): tuple(str(e).lower() for e in exts)
        for name, exts in (raw.get("types") or {}).items()
    }
    caps: dict[str, Capability] = {}
    for name, body in (raw.get("capabilities") or {}).items():
        in_types = tuple(str(x) for x in body.get("in") or ())
        out = str(body.get("out") or "")
        if not in_types or not out:
            raise _bad("capabilities.json", f"capabilities.{name}")
        caps[str(name)] = Capability(
            name=str(name),
            in_types=in_types,
            out=out,
            extra=tuple(str(x) for x in body.get("extra") or ()),
        )
    return caps, types


def parse_bridge(raw: dict[str, Any], source: str) -> Bridge:
    for field_name in ("id", "from", "to", "out_ext"):
        if not raw.get(field_name):
            raise _bad(source, field_name)
    detect = raw.get("detect")
    if not isinstance(detect, dict) or not detect:
        raise _bad(source, "detect")
    return Bridge(
        id=str(raw["id"]),
        frm=str(raw["from"]),
        to=str(raw["to"]),
        detect=dict(detect),
        run=_templates(raw.get("run"), source, "run"),
        out_ext=str(raw["out_ext"]).lstrip("."),
    )


def parse_roles(raw: dict[str, Any], source: str = "roles.json") -> RolesConfig:
    roles: dict[str, Role] = {}
    for name, body in (raw.get("roles") or {}).items():
        providers = tuple(str(x) for x in body.get("providers") or ())
        if not providers:
            raise _bad(source, f"roles.{name}.providers")
        roles[str(name)] = Role(
            name=str(name),
            providers=providers,
            worktree=bool(body.get("worktree", False)),
        )
    patterns: dict[str, tuple[str, ...]] = {}
    for name, stages in (raw.get("patterns") or {}).items():
        listed = tuple(str(s) for s in stages)
        unknown = set(listed) - STAGES
        if unknown:
            label = bi("unknown stages", "неизвестные стадии")
            raise _bad(source, f"patterns.{name} ({label}: {sorted(unknown)})")
        patterns[str(name)] = listed
    return RolesConfig(roles=roles, patterns=patterns)


def parse_recipe(raw: dict[str, Any], source: str) -> Recipe:
    rid = str(raw.get("id") or "")
    if not rid:
        raise _bad(source, "id")
    steps_raw = raw.get("steps") or []
    if not steps_raw:
        raise _bad(source, "steps")
    steps: list[Step] = []
    for index, body in enumerate(steps_raw):
        if bool(body.get("capability")) == bool(body.get("role")):
            label = bi("exactly one of capability/role", "нужен ровно один из capability/role")
            raise _bad(source, f"steps[{index}] ({label})")
        steps.append(
            Step(
                capability=body.get("capability"),
                role=body.get("role"),
                provider=body.get("provider"),
                vars={str(k): str(v) for k, v in (body.get("vars") or {}).items()},
                in_ref=body.get("in"),
                extra_in=tuple(str(x) for x in body.get("extra_in") or ()),
            )
        )
    on_quota = str(raw.get("on_quota") or "fail")
    if on_quota not in {"fail", "fallback"}:
        raise _bad(source, "on_quota")
    return Recipe(
        id=rid,
        description=bilingual(raw.get("description"), source, "description"),
        steps=tuple(steps),
        on_quota=on_quota,
    )

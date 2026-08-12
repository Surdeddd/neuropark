from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from nn.catalog import Catalog
from nn.errors import Exit, NnError
from nn.i18n import bi
from nn.iotypes import type_of
from nn.model import Recipe, Step
from nn.registry import Registry
from nn.resolve import resolve
from nn.run import Envelope, execute
from nn.runlog import last_success_map

STEP_REF = re.compile(r"^\{step(\d+)\.out\}$")


@dataclass(frozen=True)
class StepResult:
    index: int
    envelope: Envelope


def resolve_ref(ref: str, *, input_path: str, done: list[StepResult], current_index: int) -> str:
    if ref == "{input}":
        return input_path
    match = STEP_REF.match(ref)
    if not match:
        raise NnError(
            Exit.BAD_DATA,
            bi(f"unclear input reference: {ref}", f"непонятная ссылка на вход: {ref}"),
        )
    index = int(match.group(1))
    if index >= current_index:
        raise NnError(
            Exit.BAD_DATA,
            bi(
                f"reference {ref} points forward: step {current_index}"
                f" cannot wait for step {index}",
                f"ссылка {ref} смотрит вперёд: шаг {current_index} не может ждать шаг {index}",
            ),
        )
    for result in done:
        if result.index == index and result.envelope.out:
            return result.envelope.out
    raise NnError(
        Exit.BAD_DATA,
        bi(
            f"reference {ref}: step {index} has no output",
            f"ссылка {ref}: у шага {index} нет выхода",
        ),
    )


def _capability_of(step: Step) -> str:
    if step.capability:
        return step.capability
    raise NnError(
        Exit.BAD_DATA,
        bi(
            "role steps are not supported yet, use capability",
            "шаги с role пока не поддержаны — используй capability",
        ),
    )


def run_recipe(
    recipe: Recipe,
    *,
    catalog: Catalog,
    registry: Registry,
    input_path: str,
    work_dir: str | None = None,
    now: datetime | None = None,
    exhausted: frozenset[str] = frozenset(),
) -> list[StepResult]:
    """Шаги по порядку. Поле on_quota рецепта решает, что делать с исчерпанным окном:
    fail (по умолчанию) — цепочка падает кодом 6, fallback — разрешён переход
    на следующего провайдера, потому что рецепт объявил это заранее."""
    done: list[StepResult] = []
    current = input_path
    allow_fallback = recipe.on_quota == "fallback"

    for index, step in enumerate(recipe.steps):
        source = (
            resolve_ref(step.in_ref, input_path=input_path, done=done, current_index=index)
            if step.in_ref
            else current
        )
        extra = tuple(
            resolve_ref(ref, input_path=input_path, done=done, current_index=index)
            for ref in step.extra_in
        )
        choice = resolve(
            _capability_of(step),
            catalog=catalog,
            registry=registry,
            in_type=type_of(source, catalog.types),
            pin=step.provider,
            exhausted=exhausted,
            allow_fallback=allow_fallback,
            last_success=last_success_map(),
        )
        envelope = execute(
            choice,
            catalog=catalog,
            in_path=source,
            extra=extra,
            work_dir=work_dir,
            now=now,
        )
        done.append(StepResult(index=index, envelope=envelope))
        if envelope.outcome != "success" or not envelope.out:
            break
        current = envelope.out

    return done

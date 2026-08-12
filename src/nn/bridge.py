from __future__ import annotations

from collections.abc import Mapping

from nn.detect import Runner, run_detect, shell_runner
from nn.model import Bridge


def find_bridge(
    from_type: str,
    to_types: tuple[str, ...],
    bridges: Mapping[str, Bridge],
    *,
    runner: Runner = shell_runner,
) -> Bridge | None:
    """Один шаг конвертации. Цепочки из двух мостиков не ищем намеренно."""
    if from_type in to_types:
        return None
    for bridge in sorted(bridges.values(), key=lambda b: b.id):
        if bridge.frm != from_type or bridge.to not in to_types:
            continue
        if run_detect(bridge.detect, runner=runner).status != "ok":
            continue
        return bridge
    return None

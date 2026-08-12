from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

from nn.errors import Exit, NnError

_ENV_RE = re.compile(r"\$(\w+)")


def state_dir() -> Path:
    raw = os.environ.get("NN_STATE")
    path = Path(raw).expanduser() if raw else Path.home() / ".claude" / "nn"
    path.mkdir(parents=True, exist_ok=True)
    return path


def data_dir() -> Path:
    raw = os.environ.get("NN_DATA")
    if raw:
        return Path(raw).expanduser()
    return Path(__file__).resolve().parents[2]


def expand(value: str, *, env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env

    def sub(match: re.Match[str]) -> str:
        name = match.group(1)
        got = source.get(name)
        if not got:
            raise NnError(Exit.BAD_DATA, f"переменная окружения {name} не задана или пуста")
        return got

    return str(Path(_ENV_RE.sub(sub, value)).expanduser())

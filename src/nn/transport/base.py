from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from nn.errors import Exit, NnError
from nn.model import Host

AT_FILE = "@file:"


@dataclass(frozen=True)
class Executed:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    command: str


class Transport(Protocol):
    def execute(
        self,
        command: str,
        *,
        host: Host,
        timeout_s: int,
        work_dir: str,
        env: Mapping[str, str],
    ) -> Executed: ...


def resolve_env(host: Host, base: Mapping[str, str]) -> dict[str, str]:
    """Секреты в файлах хостов лежат только как @file:путь и читаются в момент запуска."""
    merged = dict(base)
    for key, value in host.env.items():
        if value.startswith(AT_FILE):
            path = Path(value[len(AT_FILE) :]).expanduser()
            if not path.is_file():
                raise NnError(
                    Exit.BAD_DATA,
                    f"host {host.id}: файл секрета {path} отсутствует (env {key})",
                )
            merged[key] = path.read_text(encoding="utf-8").strip()
        else:
            merged[key] = value
    return merged

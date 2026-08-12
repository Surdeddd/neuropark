from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from nn.errors import Exit, NnError
from nn.i18n import bi
from nn.model import Host

AT_FILE = "@file:"


@dataclass(frozen=True)
class Executed:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    command: str


@dataclass(frozen=True)
class Prepared:
    """Контекст, которым рендерятся команды, и провал подготовки, если он случился.

    Провал приходит значением, а не исключением: недоступный хост должен попасть в
    журнал прогонов как исход, иначе досье не смогут на нём учиться.
    """

    context: dict[str, str]
    failure: Executed | None = None


class Transport(Protocol):
    def prepare(
        self, context: dict[str, str], *, host: Host, run_id: str, env: Mapping[str, str]
    ) -> Prepared: ...

    def execute(
        self,
        command: str,
        *,
        host: Host,
        timeout_s: int,
        work_dir: str,
        env: Mapping[str, str],
    ) -> Executed: ...

    def collect(self) -> Executed | None:
        """Забрать выход туда, где его ждут. Вызывается после каждой попытки."""
        ...

    def finish(self) -> None:
        """Убрать за собой. Вызывается один раз, чем бы прогон ни кончился."""
        ...


def resolve_env(host: Host, base: Mapping[str, str]) -> dict[str, str]:
    """Секреты в файлах хостов лежат только как @file:путь и читаются в момент запуска."""
    merged = dict(base)
    for key, value in host.env.items():
        if value.startswith(AT_FILE):
            path = Path(value[len(AT_FILE) :]).expanduser()
            if not path.is_file():
                raise NnError(
                    Exit.BAD_DATA,
                    bi(
                        f"host {host.id}: secret file {path} is missing (env {key})",
                        f"host {host.id}: файл секрета {path} отсутствует (env {key})",
                    ),
                )
            merged[key] = path.read_text(encoding="utf-8").strip()
        else:
            merged[key] = value
    return merged

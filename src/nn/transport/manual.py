from __future__ import annotations

import shlex
from collections.abc import Mapping

from nn.errors import Exit
from nn.model import Host
from nn.transport.base import Executed, Prepared


class ManualTransport:
    """Ничего не запускает: отдаёт команду, которую нужно выполнить руками."""

    def prepare(
        self, context: dict[str, str], *, host: Host, run_id: str, env: Mapping[str, str]
    ) -> Prepared:
        return Prepared(context)

    def collect(self) -> Executed | None:
        return None

    def finish(self) -> None:
        return None

    def execute(
        self,
        command: str,
        *,
        host: Host,
        timeout_s: int,
        work_dir: str,
        env: Mapping[str, str],
    ) -> Executed:
        if host.kind == "ssh" and host.addr:
            shown = f"ssh {host.addr} {shlex.quote(command)}"
        else:
            shown = command
        return Executed(int(Exit.MANUAL), "", "", False, shown)

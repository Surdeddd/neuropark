from __future__ import annotations

import subprocess
from collections.abc import Mapping

from nn.gitenv import clean_env
from nn.model import Host
from nn.transport.base import Executed, Prepared


class LocalTransport:
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
        # Провайдер работает в work_dir, поэтому GIT_DIR и родня от вызывающего
        # процесса ему только навредят: git внутри команды ушёл бы в чужой репозиторий.
        environ = clean_env(dict(env))
        try:
            done = subprocess.run(  # noqa: S602
                command,
                shell=True,
                cwd=work_dir,
                env=environ,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            return Executed(
                124,
                stdout if isinstance(stdout, str) else stdout.decode("utf-8", "replace"),
                stderr if isinstance(stderr, str) else stderr.decode("utf-8", "replace"),
                True,
                command,
            )
        return Executed(done.returncode, done.stdout, done.stderr, False, command)

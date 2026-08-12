from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping

from nn.model import Host
from nn.transport.base import Executed


class LocalTransport:
    def execute(
        self,
        command: str,
        *,
        host: Host,
        timeout_s: int,
        work_dir: str,
        env: Mapping[str, str],
    ) -> Executed:
        environ = dict(os.environ)
        environ.update(env)
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

"""Запуск провайдера на удалённой POSIX-машине с перебросом входа и выхода.

Спека, контракт и грабли — в MEMORY_BANK/design/ssh-transport.md.
"""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from nn.detect import Runner
from nn.errors import Exit, NnError
from nn.gitenv import clean_env
from nn.i18n import bi
from nn.model import Host

from .base import Executed, Prepared

TRANSFER_TIMEOUT_S = 1800
CONTROL_TIMEOUT_S = 30
CONNECT_TIMEOUT_S = 10
DEFAULT_REMOTE_BASE = "/tmp"

# Ключи контекста, указывающие на локальные файлы, — только они и переезжают.
# vars и host.paths.* остаются как есть: это уже пути той стороны.
INPUT_KEYS = ("in", "prompt_file")
OUTPUT_KEYS = ("out",)


def remote_dir_for(host: Host, run_id: str) -> str:
    base = host.paths.get("tmp") or DEFAULT_REMOTE_BASE
    return f"{base.rstrip('/')}/nn-{run_id}"


def is_safe_remote_dir(path: str, run_id: str) -> bool:
    """Охрана для rm -rf: удаляется только то, что nn сам и создал.

    Без неё пустой run_id или подменённый host.paths.tmp превращали бы уборку
    в снос чужой директории на удалённой машине.
    """
    if not run_id or "/" in run_id or ".." in path:
        return False
    return path.startswith("/") and path.endswith(f"/nn-{run_id}")


def _text(raw: str | bytes | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "replace")
    return raw


def build_script(command: str, *, remote_dir: str, env: Mapping[str, str]) -> str:
    """Скрипт для `sh -s`: окружение и команда уходят на stdin.

    Именно stdin, а не аргумент ssh: в argv секреты видны в `ps` на той стороне,
    а на диск удалённой машины они так не попадают вообще.
    """
    lines = [f"cd {shlex.quote(remote_dir)} || exit 1"]
    lines.extend(f"export {key}={shlex.quote(value)}" for key, value in sorted(env.items()))
    lines.append(command)
    return "\n".join(lines) + "\n"


def runner_for(host: Host, env: Mapping[str, str] | None = None) -> Runner:
    """Runner, исполняющий команды на удалённой машине — для детекта и версий.

    Тот же интерфейс, что у локального `shell_runner`, поэтому детект переезжает
    на чужую машину без второй реализации. Окружение уходит через stdin вместе с
    командой: ключи не светятся в `ps` на той стороне.
    """
    options = [
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={CONNECT_TIMEOUT_S}",
        *host.ssh_options,
    ]
    addr = host.addr or host.id
    exports = "\n".join(
        f"export {key}={shlex.quote(value)}" for key, value in sorted((env or {}).items())
    )

    def run(command: str, *, timeout: float) -> tuple[int, str, str]:
        script = f"{exports}\n{command}\n" if exports else f"{command}\n"
        try:
            done = subprocess.run(
                ["ssh", *options, addr, "sh", "-s"],
                input=script,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env=clean_env(),
            )
        except subprocess.TimeoutExpired:
            return (124, "", "timeout")
        except OSError as exc:
            return (127, "", str(exc))
        return (done.returncode, done.stdout, done.stderr)

    return run


@dataclass
class SshTransport:
    """Один экземпляр — один прогон: помнит адрес, свою директорию и что забрать."""

    ssh_bin: str = "ssh"
    ssh_options: tuple[str, ...] = ()
    remote_dir: str | None = None
    addr: str | None = None
    downloads: list[tuple[str, str]] = field(default_factory=list)
    run_id: str = ""

    def _options(self) -> list[str]:
        # BatchMode обязателен: без него ssh зависает на приглашении пароля и
        # съедает весь таймаут вместо честного отказа.
        return [
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={CONNECT_TIMEOUT_S}",
            *self.ssh_options,
        ]

    def _require_addr(self, host: Host) -> str:
        if not host.addr:
            raise NnError(
                Exit.BAD_DATA,
                bi(
                    f"host {host.id}: kind=ssh needs addr",
                    f"host {host.id}: для kind=ssh нужен addr",
                ),
            )
        return host.addr

    def _run(self, argv: Sequence[str], *, timeout_s: int, stdin: str | None = None) -> Executed:
        shown = " ".join(shlex.quote(part) for part in argv)
        try:
            done = subprocess.run(
                list(argv),
                input=stdin,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
                env=clean_env(),
            )
        except subprocess.TimeoutExpired as exc:
            return Executed(124, _text(exc.stdout), _text(exc.stderr), True, shown)
        except OSError as exc:
            return Executed(127, "", str(exc), False, shown)
        return Executed(done.returncode, done.stdout, done.stderr, False, shown)

    def _stream(
        self,
        argv: Sequence[str],
        *,
        timeout_s: int,
        stdin_file: Path | None = None,
        stdout_file: Path | None = None,
    ) -> Executed:
        """Перенос файла потоком: содержимое не попадает в память целиком.

        Файлы носит ssh, а не scp: у scp порт задаётся -P против ssh-ного -p, и он
        требует sftp-подсистему на сервере, которой на закрытых серверах может не
        быть. Оба случая поймал живой прогон — так что переносим тем же каналом,
        которым и запускаем.
        """
        shown = " ".join(shlex.quote(part) for part in argv)
        source = stdin_file.open("rb") if stdin_file else subprocess.DEVNULL
        sink = stdout_file.open("wb") if stdout_file else subprocess.PIPE
        try:
            done = subprocess.run(
                list(argv),
                stdin=source,
                stdout=sink,
                stderr=subprocess.PIPE,
                timeout=timeout_s,
                check=False,
                env=clean_env(),
            )
        except subprocess.TimeoutExpired:
            return Executed(124, "", "", True, shown)
        except OSError as exc:
            return Executed(127, "", str(exc), False, shown)
        finally:
            if stdin_file and source is not subprocess.DEVNULL:
                source.close()  # type: ignore[union-attr]
            if stdout_file and sink is not subprocess.PIPE:
                sink.close()  # type: ignore[union-attr]
        stderr = done.stderr.decode("utf-8", "replace") if done.stderr else ""
        return Executed(done.returncode, "", stderr, False, shown)

    def _upload(self, local: Path, remote_path: str) -> Executed:
        argv = [self.ssh_bin, *self._options(), str(self.addr)]
        argv += ["sh", "-c", f"cat > {shlex.quote(remote_path)}"]
        return self._stream(argv, timeout_s=TRANSFER_TIMEOUT_S, stdin_file=local)

    def _download(self, remote_path: str, local: Path) -> Executed:
        argv = [self.ssh_bin, *self._options(), str(self.addr)]
        argv += ["cat", "--", remote_path]
        return self._stream(argv, timeout_s=TRANSFER_TIMEOUT_S, stdout_file=local)

    def prepare(
        self, context: dict[str, str], *, host: Host, run_id: str, env: Mapping[str, str]
    ) -> Prepared:
        self.addr = self._require_addr(host)
        self.run_id = run_id
        self.remote_dir = self.remote_dir or remote_dir_for(host, run_id)

        made = self._run(
            [self.ssh_bin, *self._options(), self.addr, "mkdir", "-p", "--", self.remote_dir],
            timeout_s=CONTROL_TIMEOUT_S,
        )
        if made.exit_code != 0 or made.timed_out:
            return Prepared(context, failure=made)

        remote = dict(context)
        uploads: list[tuple[Path, str]] = []
        for key, value in context.items():
            if not value:
                continue
            if key in INPUT_KEYS or key.startswith("extra"):
                local = Path(value)
                if not local.is_file():
                    continue
                remote[key] = f"{self.remote_dir}/{local.name}"
                uploads.append((local, remote[key]))
            elif key in OUTPUT_KEYS:
                remote[key] = f"{self.remote_dir}/{Path(value).name}"
                self.downloads.append((remote[key], value))
            elif key == "tmp":
                remote[key] = f"{self.remote_dir}/{Path(value).name}"
            elif key == "dir":
                remote[key] = self.remote_dir

        if remote.get("out"):
            remote["out_base"] = str(Path(remote["out"]).with_suffix(""))

        for local, remote_path in uploads:
            sent = self._upload(local, remote_path)
            if sent.exit_code != 0 or sent.timed_out:
                return Prepared(context, failure=sent)

        return Prepared(remote)

    def execute(
        self,
        command: str,
        *,
        host: Host,
        timeout_s: int,
        work_dir: str,
        env: Mapping[str, str],
    ) -> Executed:
        addr = self.addr or self._require_addr(host)
        remote_dir = self.remote_dir or remote_dir_for(host, self.run_id)
        result = self._run(
            [self.ssh_bin, *self._options(), addr, "sh", "-s"],
            timeout_s=timeout_s,
            stdin=build_script(command, remote_dir=remote_dir, env=env),
        )
        # В журнале и в конверте остаётся команда провайдера, а не обёртка ssh:
        # человек должен видеть то, что запускалось на удалённой машине.
        return Executed(result.exit_code, result.stdout, result.stderr, result.timed_out, command)

    def collect(self) -> Executed | None:
        if self.addr is None or self.remote_dir is None:
            return None
        return self._fetch()

    def finish(self) -> None:
        if self.addr is None or self.remote_dir is None:
            return None
        self._cleanup()
        return None

    def _remote_names(self) -> list[str]:
        argv = [self.ssh_bin, *self._options(), str(self.addr)]
        argv += ["ls", "-1", "--", str(self.remote_dir)]
        listing = self._run(argv, timeout_s=CONTROL_TIMEOUT_S)
        return [name for name in listing.stdout.splitlines() if name.strip()]

    def _fetch(self) -> Executed | None:
        if not self.downloads:
            return None
        names = self._remote_names()
        for remote_path, local_path in self.downloads:
            target = Path(local_path)
            wanted = _matching(names, remote_path)
            if not wanted:
                # Выхода нет — это не отказ транспорта: классификация исхода увидит
                # отсутствующий файл и назовёт прогон тем, чем он был.
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            for name in wanted:
                # Сам выход кладём туда, где его ждут; попутные файлы — рядом,
                # под их собственными именами.
                landing = target if name == Path(remote_path).name else target.parent / name
                got = self._download(f"{self.remote_dir}/{name}", landing)
                if got.exit_code != 0 or got.timed_out:
                    landing.unlink(missing_ok=True)
                    return got
        return None

    def _cleanup(self) -> None:
        if self.remote_dir is None or not is_safe_remote_dir(self.remote_dir, self.run_id):
            return
        self._run(
            [self.ssh_bin, *self._options(), str(self.addr), "rm", "-rf", "--", self.remote_dir],
            timeout_s=CONTROL_TIMEOUT_S,
        )


def _matching(names: Sequence[str], remote_path: str) -> list[str]:
    """Сам выход плюс файлы с тем же стемом: провайдер мог писать {out_base}.ext."""
    target = Path(remote_path).name
    stem = Path(target).with_suffix("").name
    exact = [name for name in names if name == target]
    siblings = [
        name for name in names if name != target and Path(name).with_suffix("").name == stem
    ]
    return exact + siblings

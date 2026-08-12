from __future__ import annotations

from nn.errors import Exit, NnError
from nn.i18n import bi
from nn.model import Host
from nn.transport.base import Executed, Prepared, Transport, resolve_env
from nn.transport.local import LocalTransport
from nn.transport.manual import ManualTransport
from nn.transport.ssh import SshTransport

__all__ = [
    "Executed",
    "LocalTransport",
    "ManualTransport",
    "Prepared",
    "SshTransport",
    "Transport",
    "get_transport",
    "resolve_env",
]


def get_transport(host: Host) -> Transport:
    if host.kind == "manual" or not host.auto:
        return ManualTransport()
    if host.kind == "local":
        return LocalTransport()
    if host.kind == "ssh":
        # Порт, ключ, jump-хост и прочее берутся из файла хоста; для постоянных
        # настроек правильнее ~/.ssh/config, поэтому это поле необязательное.
        return SshTransport(ssh_options=tuple(host.ssh_options))
    raise NnError(
        Exit.BAD_DATA,
        bi(
            f"transport {host.kind} (host {host.id}) is not implemented;"
            " set auto: false to get the command for a manual run",
            f"транспорт {host.kind} (хост {host.id}) не реализован;"
            " поставь auto: false, чтобы получать команду для ручного запуска",
        ),
    )

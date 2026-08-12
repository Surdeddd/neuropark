from __future__ import annotations

from nn.errors import Exit, NnError
from nn.i18n import bi
from nn.model import Host
from nn.transport.base import Executed, Transport, resolve_env
from nn.transport.local import LocalTransport
from nn.transport.manual import ManualTransport

__all__ = [
    "Executed",
    "LocalTransport",
    "ManualTransport",
    "Transport",
    "get_transport",
    "resolve_env",
]


def get_transport(host: Host) -> Transport:
    if host.kind == "manual" or not host.auto:
        return ManualTransport()
    if host.kind == "local":
        return LocalTransport()
    raise NnError(
        Exit.BAD_DATA,
        bi(
            f"transport {host.kind} (host {host.id}) is not implemented;"
            " set auto: false to get the command for a manual run",
            f"транспорт {host.kind} (хост {host.id}) не реализован;"
            " поставь auto: false, чтобы получать команду для ручного запуска",
        ),
    )

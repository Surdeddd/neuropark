from __future__ import annotations

from enum import IntEnum


class Exit(IntEnum):
    OK = 0
    NO_PROVIDER = 2
    MANUAL = 3
    PROVIDER_FAILED = 4
    REGISTRY_STALE = 5
    QUOTA = 6
    BAD_DATA = 7
    BAD_IO = 8


class NnError(Exception):
    def __init__(self, code: Exit, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

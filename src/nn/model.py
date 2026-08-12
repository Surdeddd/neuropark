from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Provider:
    id: str
    capability: str
    kind: str
    detect: dict[str, Any]
    io_in: tuple[str, ...]
    io_out: str
    notes: str
    source: str
    out_ext: str | None = None
    host: str = "local"
    rank: int = 0
    version_cmd: str | None = None
    vars: dict[str, str] = field(default_factory=dict)
    pre: dict[str, str] = field(default_factory=dict)
    run: dict[str, str] = field(default_factory=dict)
    post: dict[str, str] = field(default_factory=dict)
    adapter: str | None = None
    timeout_s: int = 900
    window_h: float | None = None
    soft_cap_calls: int | None = None
    quota_patterns: tuple[str, ...] = ()
    requires_key: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    vendor: str | None = None

    @property
    def vendor_name(self) -> str:
        return self.vendor or self.id.split("-")[0]


@dataclass(frozen=True)
class Host:
    id: str
    kind: str
    addr: str | None = None
    os: str | None = None
    auto: bool = True
    probe: str | None = None
    paths: dict[str, str] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    notes: str = ""


@dataclass(frozen=True)
class Capability:
    name: str
    in_types: tuple[str, ...]
    out: str
    extra: tuple[str, ...] = ()


@dataclass(frozen=True)
class Bridge:
    id: str
    frm: str
    to: str
    detect: dict[str, Any]
    run: dict[str, str]
    out_ext: str


@dataclass(frozen=True)
class Step:
    capability: str | None = None
    role: str | None = None
    provider: str | None = None
    vars: dict[str, str] = field(default_factory=dict)
    in_ref: str | None = None
    extra_in: tuple[str, ...] = ()


@dataclass(frozen=True)
class Recipe:
    id: str
    description: str
    steps: tuple[Step, ...]
    on_quota: str = "fail"


@dataclass(frozen=True)
class Role:
    name: str
    providers: tuple[str, ...]
    worktree: bool = False


@dataclass(frozen=True)
class RolesConfig:
    roles: dict[str, Role] = field(default_factory=dict)
    patterns: dict[str, tuple[str, ...]] = field(default_factory=dict)

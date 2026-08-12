from __future__ import annotations

import json
import platform
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from nn.errors import Exit, NnError
from nn.paths import state_dir


@dataclass(frozen=True)
class Entry:
    provider: str
    host: str
    status: str
    reason: str = ""
    version: str | None = None
    last_seen: str | None = None


@dataclass(frozen=True)
class Registry:
    hostname: str
    generated_at: str
    entries: dict[str, Entry] = field(default_factory=dict)

    def get(self, provider: str) -> Entry | None:
        return self.entries.get(provider)

    def ok(self, provider: str) -> bool:
        entry = self.entries.get(provider)
        return entry is not None and entry.status == "ok"


def hostname() -> str:
    return platform.node().split(".")[0] or "unknown"


def registry_path(host: str | None = None) -> Path:
    return state_dir() / f"registry.{host or hostname()}.json"


def save(reg: Registry) -> Path:
    path = registry_path(reg.hostname)
    payload = {
        "hostname": reg.hostname,
        "generated_at": reg.generated_at,
        "entries": {key: asdict(entry) for key, entry in sorted(reg.entries.items())},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load(host: str | None = None) -> Registry:
    path = registry_path(host)
    if not path.is_file():
        raise NnError(Exit.REGISTRY_STALE, f"реестра {path.name} нет — сделай nn scan")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return Registry(
        hostname=str(payload["hostname"]),
        generated_at=str(payload["generated_at"]),
        entries={key: Entry(**value) for key, value in payload.get("entries", {}).items()},
    )


def is_expired(reg: Registry, *, now: datetime, max_age_days: int = 30) -> bool:
    return datetime.fromisoformat(reg.generated_at) < now - timedelta(days=max_age_days)

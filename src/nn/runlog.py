from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from nn.paths import state_dir

SUCCESS = "success"


@dataclass(frozen=True)
class RunRecord:
    ts: str
    run_id: str
    provider: str
    capability: str
    host: str
    in_type: str | None
    out: str | None
    exit_code: int
    outcome: str
    ms: int
    stderr_tail: str


def log_path() -> Path:
    return state_dir() / "runs.jsonl"


def append(record: RunRecord) -> None:
    line = json.dumps(asdict(record), ensure_ascii=False)
    with log_path().open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def read_all() -> list[RunRecord]:
    path = log_path()
    if not path.is_file():
        return []
    records: list[RunRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            records.append(RunRecord(**payload))
        except (json.JSONDecodeError, TypeError):
            continue
    return records


def last_success_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for record in read_all():
        if record.outcome != SUCCESS:
            continue
        current = mapping.get(record.provider)
        if current is None or record.ts > current:
            mapping[record.provider] = record.ts
    return mapping

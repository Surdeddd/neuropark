from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nn.detect import Runner, glob_paths, run_detect, shell_runner, which
from nn.errors import Exit, NnError
from nn.i18n import bi
from nn.paths import data_dir, user_data_dir


@dataclass(frozen=True)
class Candidate:
    id: str
    capability: str
    found: bool
    reason: str
    model: str | None = None
    needs_editing: bool = False
    manifest: dict[str, Any] | None = None


def priors_path(root: Path | None = None) -> Path:
    return (root or data_dir()) / "priors.json"


def load_priors(root: Path | None = None) -> list[dict[str, Any]]:
    path = priors_path(root)
    if not path.is_file():
        raise NnError(
            Exit.BAD_DATA,
            bi(f"{path} is missing", f"{path} отсутствует"),
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    priors = payload.get("priors")
    if not isinstance(priors, list):
        raise NnError(
            Exit.BAD_DATA, bi("priors.json: no priors list", "priors.json: нет списка priors")
        )
    return [item for item in priors if isinstance(item, dict)]


def _pick_model(patterns: list[str], prefer: list[str]) -> Path | None:
    """Названный в prefer файл важнее размера: у rnnoise профили одинаковы по весу,
    но речевой подходит для голоса, а самый крупный — нет. Иначе берём крупнейший."""
    found: list[Path] = []
    for pattern in patterns:
        found.extend(path for path in glob_paths(pattern) if path.is_file())
    if not found:
        return None
    for wanted in prefer:
        for path in found:
            if path.name == wanted:
                return path
    return max(found, key=lambda path: path.stat().st_size)


def evaluate(prior: dict[str, Any], *, runner: Runner = shell_runner) -> Candidate:
    probe = prior.get("probe") or {}
    capability = str(prior.get("capability") or "")
    pid = str(prior.get("id") or "")

    binary = probe.get("bin")
    if binary and which(str(binary)) is None:
        return Candidate(pid, capability, False, bi(f"no {binary}", f"нет {binary}"))

    module = probe.get("python")
    if module:
        result = run_detect({"python": module}, runner=runner)
        if result.status != "ok":
            return Candidate(pid, capability, False, result.reason)

    endpoint = probe.get("http")
    if endpoint:
        result = run_detect({"http": endpoint}, runner=runner)
        if result.status != "ok":
            return Candidate(pid, capability, False, result.reason)

    model: str | None = None
    globs = probe.get("model_glob")
    if globs:
        prefer = [str(item) for item in probe.get("model_prefer") or ()]
        picked = _pick_model([str(item) for item in globs], prefer)
        if picked is None:
            return Candidate(pid, capability, False, bi("no model files", "нет файлов модели"))
        model = str(picked)

    return Candidate(
        pid,
        capability,
        True,
        "",
        model=model,
        needs_editing=bool(prior.get("needs_editing")),
        manifest=build_manifest(prior, model),
    )


def build_detect(probe: dict[str, Any], model: str | None) -> dict[str, Any]:
    """probe описывает, как ИСКАТЬ инструмент; detect — как проверять его наличие потом.

    Пути к модели фиксируются найденным файлом: манифест должен ломаться, если
    именно эта модель исчезла, а не молча брать другую.
    """
    detect: dict[str, Any] = {}
    for key in ("bin", "python", "http"):
        if probe.get(key):
            detect[key] = probe[key]
    if model:
        detect["files"] = [model]
    return detect


def build_manifest(prior: dict[str, Any], model: str | None) -> dict[str, Any]:
    skip = {"probe", "needs_editing"}
    manifest = {key: value for key, value in prior.items() if key not in skip}
    detect = build_detect(prior.get("probe") or {}, model)
    if not detect:
        detect = {"bin": "true"}
    manifest["detect"] = detect
    variables = dict(manifest.get("vars") or {})
    if model:
        variables["model"] = model
    if variables:
        manifest["vars"] = variables
    return manifest


def write_manifests(candidates: list[Candidate], *, target: Path | None = None) -> list[Path]:
    root = (target or user_data_dir()) / "providers"
    root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for item in candidates:
        if not item.found or item.manifest is None:
            continue
        path = root / f"{item.id}.json"
        path.write_text(
            json.dumps(item.manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        written.append(path)
    return written


def ensure_local_host(target: Path | None = None) -> Path:
    """Без hosts/local.json каталог не грузится, поэтому init его создаёт."""
    root = (target or user_data_dir()) / "hosts"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "local.json"
    if path.is_file():
        return path
    payload = {
        "id": "local",
        "kind": "local",
        "auto": True,
        "paths": {},
        "notes": bi("this machine", "эта машина"),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def discover(*, root: Path | None = None, runner: Runner = shell_runner) -> list[Candidate]:
    return [evaluate(prior, runner=runner) for prior in load_priors(root)]

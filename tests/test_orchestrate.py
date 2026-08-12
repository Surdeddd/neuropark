"""Оркестрация на фейковых «моделях»: подписки не тратятся, сети нет."""

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nn.adapt import build
from nn.catalog import Catalog
from nn.errors import Exit, NnError
from nn.model import Capability, Host, Provider, Role, RolesConfig
from nn.orchestrate import STAGE_ROLES, orchestrate, report
from nn.registry import Entry, Registry
from nn.resolve import resolve_role

NOW = datetime(2026, 8, 12, 15, 0, tzinfo=UTC)
LOCAL = Host(id="local", kind="local")
TYPES = {"text": ("txt",)}
CAPS = {"text": Capability("text", ("text",), "text")}
LONG = "достаточно длинный ответ модели чтобы пройти порог пустоты"


def prov(pid: str, *, rank: int = 0, vendor: str | None = None, run: str | None = None) -> Provider:
    return Provider(
        id=pid,
        capability="text",
        kind="agent",
        detect={"bin": "printf"},
        io_in=("text",),
        io_out="text",
        notes="фейк",
        source=f"providers/{pid}.json",
        rank=rank,
        vendor=vendor,
        run={"": run or f"printf '{LONG} от {pid}' > {{out}}"},
    )


def build_catalog(providers: list[Provider], roles: RolesConfig) -> tuple[Catalog, Registry]:
    catalog = Catalog(
        providers={p.id: p for p in providers},
        hosts={"local": LOCAL},
        capabilities=CAPS,
        types=TYPES,
        bridges={},
        recipes={},
        roles=roles,
    )
    registry = Registry(
        hostname="testbox",
        generated_at=NOW.isoformat(),
        entries={p.id: Entry(p.id, "local", "ok", "", None, NOW.isoformat()) for p in providers},
    )
    return catalog, registry


def full_roles(worktree: bool = True) -> RolesConfig:
    return RolesConfig(
        roles={
            "spec": Role("spec", ("alpha-cli",)),
            "mechanics": Role("mechanics", ("beta-cli",), worktree=worktree),
            "review": Role("review", ("alpha-cli", "beta-cli")),
            "core": Role("core", ("alpha-cli",)),
        },
        patterns={"default": ("spec", "work", "cross-review", "verdict"), "quick": ("work",)},
    )


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@e.com"], cwd=root, check=True, capture_output=True
    )
    (root / "file.txt").write_text("исходник\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "1"], cwd=root, check=True, capture_output=True)
    return root


def test_task_reaches_every_stage_even_without_spec():
    """Регрессия живого прогона: в паттерне quick исполнителю уходила пустая спека."""
    from nn.orchestrate import _prompt_for

    for stage in ("spec", "work", "cross-review", "verdict"):
        prompt = _prompt_for(stage, "починить парсер", "", [], [])
        assert "починить парсер" in prompt, stage
        assert "Спека:\n\n" not in prompt, stage


def test_spec_is_added_as_context_when_present():
    from nn.orchestrate import _prompt_for

    prompt = _prompt_for("work", "задача", "текст спеки", [], [])
    assert "задача" in prompt
    assert "текст спеки" in prompt


def test_stage_role_mapping_is_fixed():
    assert STAGE_ROLES["spec"] == "spec"
    assert STAGE_ROLES["cross-review"] == "review"
    assert STAGE_ROLES["verdict"] == "core"


def test_resolve_role_walks_declared_chain():
    catalog, registry = build_catalog(
        [prov("alpha-cli"), prov("beta-cli")],
        RolesConfig(roles={"review": Role("review", ("beta-cli", "alpha-cli"))}),
    )
    choice = resolve_role("review", catalog=catalog, registry=registry)
    assert choice.provider.id == "beta-cli"


def test_resolve_role_skips_unavailable_and_records_reason():
    catalog, registry = build_catalog(
        [prov("alpha-cli"), prov("beta-cli")],
        RolesConfig(roles={"review": Role("review", ("ghost", "alpha-cli"))}),
    )
    choice = resolve_role("review", catalog=catalog, registry=registry)
    assert choice.provider.id == "alpha-cli"
    assert any("нет такого манифеста" in r.reason for r in choice.rejected)


def test_resolve_role_excludes_vendor():
    catalog, registry = build_catalog(
        [prov("alpha-cli", vendor="alpha"), prov("beta-cli", vendor="beta")],
        RolesConfig(roles={"review": Role("review", ("alpha-cli", "beta-cli"))}),
    )
    choice = resolve_role(
        "review", catalog=catalog, registry=registry, exclude_vendors=frozenset({"alpha"})
    )
    assert choice.provider.id == "beta-cli"


def test_resolve_role_unknown_role_is_no_provider():
    catalog, registry = build_catalog([prov("alpha-cli")], RolesConfig())
    with pytest.raises(NnError) as err:
        resolve_role("нету", catalog=catalog, registry=registry)
    assert err.value.code == Exit.NO_PROVIDER


def test_vendor_defaults_to_id_prefix():
    assert prov("claude-text").vendor_name == "claude"
    assert prov("x", vendor="явный").vendor_name == "явный"


def test_full_pattern_runs_four_stages(repo):
    catalog, registry = build_catalog(
        [prov("alpha-cli", vendor="alpha"), prov("beta-cli", vendor="beta")], full_roles()
    )
    results = orchestrate("починить парсер", catalog=catalog, registry=registry, repo=repo, now=NOW)
    assert [item.stage for item in results] == ["spec", "work", "cross-review", "verdict"]
    assert all(item.envelope.outcome == "success" for item in results)


def test_review_goes_to_another_vendor(repo):
    catalog, registry = build_catalog(
        [prov("alpha-cli", vendor="alpha"), prov("beta-cli", vendor="beta")], full_roles()
    )
    results = orchestrate("задача", catalog=catalog, registry=registry, repo=repo, now=NOW)
    work = next(item for item in results if item.stage == "work")
    review = next(item for item in results if item.stage == "cross-review")
    author = catalog.providers[work.provider].vendor_name
    reviewer = catalog.providers[review.provider].vendor_name
    assert author != reviewer


def test_work_stage_produces_patch_and_leaves_repo_untouched(repo):
    writer = prov(
        "beta-cli",
        vendor="beta",
        run="printf 'правка модели\\n' > file.txt; printf '%s' 'сделал правку в file.txt' > {out}",
    )
    catalog, registry = build_catalog([prov("alpha-cli", vendor="alpha"), writer], full_roles())
    results = orchestrate("правь файл", catalog=catalog, registry=registry, repo=repo, now=NOW)
    work = next(item for item in results if item.stage == "work")
    assert work.patch is not None
    assert "правка модели" in Path(work.patch).read_text(encoding="utf-8")
    # оригинал не тронут и коммитов не появилось
    assert (repo / "file.txt").read_text(encoding="utf-8") == "исходник\n"
    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=repo, capture_output=True, text=True, check=True
    )
    assert len(log.stdout.strip().splitlines()) == 1


def test_fanout_creates_several_work_results(repo):
    catalog, registry = build_catalog(
        [prov("alpha-cli", vendor="alpha"), prov("beta-cli", vendor="beta")], full_roles()
    )
    results = orchestrate(
        "задача", catalog=catalog, registry=registry, repo=repo, fanout=3, now=NOW
    )
    assert len([item for item in results if item.stage == "work"]) == 3


def test_unknown_pattern_is_bad_data(repo):
    catalog, registry = build_catalog([prov("alpha-cli")], full_roles())
    with pytest.raises(NnError) as err:
        orchestrate("з", catalog=catalog, registry=registry, repo=repo, pattern="нету", now=NOW)
    assert err.value.code == Exit.BAD_DATA


def test_worktree_disabled_role_runs_in_place(repo):
    catalog, registry = build_catalog(
        [prov("alpha-cli", vendor="alpha"), prov("beta-cli", vendor="beta")],
        full_roles(worktree=False),
    )
    results = orchestrate(
        "задача", catalog=catalog, registry=registry, repo=repo, pattern="quick", now=NOW
    )
    work = next(item for item in results if item.stage == "work")
    assert work.patch is None


def test_report_marks_patch_as_not_applied(repo):
    writer = prov(
        "beta-cli",
        vendor="beta",
        run="printf 'x\\n' > file.txt; printf '%s' 'готово, правка внесена' > {out}",
    )
    catalog, registry = build_catalog([prov("alpha-cli", vendor="alpha"), writer], full_roles())
    results = orchestrate("з", catalog=catalog, registry=registry, repo=repo, now=NOW)
    text = report(results)
    assert "НЕ применён" in text
    assert "мерж твой" in text


def test_adapt_builds_chain_from_available_text_providers():
    catalog, registry = build_catalog(
        [prov("alpha-cli", rank=9), prov("beta-cli", rank=1)], RolesConfig()
    )
    result = build(catalog, registry)
    assert result.roles["core"].providers[0] == "alpha-cli"
    assert result.roles["mechanics"].worktree is True
    assert "default" in result.patterns
    # payload обязан быть валидным для parse_roles, иначе adapt пишет мусор
    from nn.schema import parse_roles

    parsed = parse_roles(result.to_payload())
    assert parsed.roles["core"].providers[0] == "alpha-cli"


def test_adapt_prefers_self_declared_roles():
    hinted = Provider(
        id="beta-cli",
        capability="text",
        kind="agent",
        detect={"bin": "printf"},
        io_in=("text",),
        io_out="text",
        notes="n",
        source="providers/beta-cli.json",
        rank=1,
        run={"": "true"},
        roles=("core",),
    )
    catalog, registry = build_catalog([prov("alpha-cli", rank=9), hinted], RolesConfig())
    assert build(catalog, registry).roles["core"].providers[0] == "beta-cli"


def test_adapt_skips_unavailable_providers():
    catalog, registry = build_catalog([prov("alpha-cli")], RolesConfig())
    registry = Registry(
        hostname="testbox",
        generated_at=NOW.isoformat(),
        entries={"alpha-cli": Entry("alpha-cli", "local", "missing", "нет бинаря")},
    )
    assert build(catalog, registry).roles == {}

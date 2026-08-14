"""Команды CLI, у которых до сих пор был только свип: init, adapt, learn, burn, orchestrate.

Свип проверял, что они не падают. Здесь — что они делают ровно то, что обещают,
и в JSON-режиме отдают ту форму, на которую можно опереться скриптом.
"""

import json
import pathlib
import subprocess

import pytest

from nn.cli import main
from nn.errors import Exit

REPO = pathlib.Path(__file__).resolve().parents[1]

TEXT_PROVIDER = {
    "id": "alpha-text",
    "capability": "text",
    "kind": "agent",
    "vendor": "alpha",
    "rank": 10,
    "detect": {"bin": "sh"},
    "io": {"in": ["text"], "out": "text"},
    "run": "cat {prompt_file} > {out}; printf ' ALPHA-DONE-AND-LONG-ENOUGH' >> {out}",
    "roles": ["spec", "mechanics", "core"],
    "notes": {"en": "fake alpha", "ru": "фейковый альфа"},
}
BETA_PROVIDER = dict(
    TEXT_PROVIDER,
    id="beta-text",
    vendor="beta",
    rank=5,
    run="cat {prompt_file} > {out}; printf ' BETA-DONE-AND-LONG-ENOUGH' >> {out}",
    roles=["review", "core"],
    notes={"en": "fake beta", "ru": "фейковый бета"},
)
CAPS = {
    "types": {"text": ["txt"], "audio": ["wav"], "srt": ["srt"]},
    "capabilities": {"text": {"in": ["text"], "out": "text"}},
}


@pytest.fixture
def park(monkeypatch, tmp_path):
    data = tmp_path / "data"
    (data / "providers").mkdir(parents=True)
    (data / "hosts").mkdir(parents=True)
    for provider in (TEXT_PROVIDER, BETA_PROVIDER):
        (data / "providers" / f"{provider['id']}.json").write_text(
            json.dumps(provider), encoding="utf-8"
        )
    (data / "hosts" / "local.json").write_text(
        json.dumps({"id": "local", "kind": "local"}), encoding="utf-8"
    )
    (data / "capabilities.json").write_text(json.dumps(CAPS), encoding="utf-8")
    # NN_DATA подменяет поставляемый каталог целиком, а priors.json — часть поставки:
    # без него `nn init` честно отказывается кодом 7. Прайор здесь свой и опирается
    # на `sh`, который есть на любой POSIX-машине: с репозиторными прайорами тест
    # зависел бы от того, что установлено у прогоняющего, и падал на чистом раннере.
    (data / "priors.json").write_text(
        json.dumps(
            {
                "priors": [
                    {
                        "id": "shell-echo",
                        "capability": "text",
                        "kind": "tool",
                        "probe": {"bin": "sh"},
                        "io": {"in": ["text"], "out": "text"},
                        "run": "cat {prompt_file} > {out}",
                        "notes": {"en": "always present", "ru": "есть всегда"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (data / "dossier-rules.json").write_text(
        (REPO / "dossier-rules.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    monkeypatch.setenv("NN_DATA", str(data))
    monkeypatch.setenv("NN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("NN_LANG", "en")
    return tmp_path


def test_init_dry_run_writes_nothing(park, capsys):
    assert main(["init", "--dry-run"]) == int(Exit.OK)
    out = capsys.readouterr().out
    assert "shell-echo" in out
    written = list((park / "home").rglob("*.json")) if (park / "home").exists() else []
    assert written == [], written


def test_init_writes_manifests_that_the_catalog_can_read(park, capsys):
    assert main(["init"]) == int(Exit.OK)
    assert "written manifests" in capsys.readouterr().out
    manifests = sorted((park / "home" / "providers").glob("*.json"))
    assert [path.stem for path in manifests] == ["shell-echo"]
    for path in manifests:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["id"] == path.stem
        assert payload["detect"], "манифест без detect бесполезен"


def test_adapt_writes_roles_and_names_the_file(park, capsys):
    main(["scan"])
    capsys.readouterr()
    assert main(["adapt"]) == int(Exit.OK)
    out = capsys.readouterr().out
    roles = park / "home" / "roles.json"
    assert roles.is_file(), out
    payload = json.loads(roles.read_text(encoding="utf-8"))
    assert "review" in payload["roles"]
    # Объявивший роль идёт первым, остальные остаются хвостом цепочки — это и есть
    # фолбэк роли, а не «только объявившие».
    assert payload["roles"]["review"]["providers"][0] == "beta-text"
    assert "alpha-text" in payload["roles"]["review"]["providers"]
    assert str(roles) in out


def test_adapt_json_names_what_it_holds(park, capsys):
    """Ключ `roles` обязан держать роли, а не путь до файла с ними."""
    main(["scan"])
    capsys.readouterr()
    assert main(["--json", "adapt"]) == int(Exit.OK)
    payload = json.loads(capsys.readouterr().out)
    assert payload["path"].endswith("roles.json")
    assert payload["roles"]["core"]["providers"], payload
    assert "patterns" in payload


def test_learn_on_an_empty_log_says_so(park, capsys):
    main(["scan"])
    capsys.readouterr()
    assert main(["learn"]) == int(Exit.OK)
    assert "nothing new" in capsys.readouterr().out


def test_learn_distils_failures_into_a_dossier(park, capsys):
    main(["scan"])
    broken = json.loads((park / "data" / "providers" / "alpha-text.json").read_text())
    broken["run"] = "echo 'ModuleNotFoundError: No module named mlx_audio' >&2; exit 1"
    (park / "data" / "providers" / "alpha-text.json").write_text(json.dumps(broken))
    main(["scan"])
    for _ in range(3):
        main(["run", "text", "--prompt", "hi", "--provider", "alpha-text", "--retries", "0"])
    capsys.readouterr()

    assert main(["learn"]) == int(Exit.OK)
    dossier = park / "state" / "dossiers" / "alpha-text.md"
    assert dossier.is_file()
    body = dossier.read_text(encoding="utf-8")
    assert "observed" in body
    assert "interpreter" in body or "интерпретатор" in body


def test_burn_without_yes_only_proposes(park, capsys, tmp_path):
    quota_aware = dict(TEXT_PROVIDER, window_h=5, soft_cap_calls=5)
    (park / "data" / "providers" / "alpha-text.json").write_text(json.dumps(quota_aware))
    main(["scan"])
    source = tmp_path / "note.txt"
    source.write_text("длинная строка для порога пустоты в классификаторе", encoding="utf-8")
    capsys.readouterr()

    assert main(["burn", "add", "text", str(source)]) == int(Exit.OK)
    assert main(["burn", "run"]) == int(Exit.OK)
    out = capsys.readouterr().out
    assert "--yes" in out, "без флага должно быть только предложение"
    assert not list((park / "state" / "out").glob("*.txt")), "ничего не должно было запуститься"


def test_burn_with_yes_executes_and_empties_the_queue(park, capsys, tmp_path):
    quota_aware = dict(TEXT_PROVIDER, window_h=5, soft_cap_calls=5)
    (park / "data" / "providers" / "alpha-text.json").write_text(json.dumps(quota_aware))
    main(["scan"])
    source = tmp_path / "note.txt"
    source.write_text("длинная строка для порога пустоты в классификаторе", encoding="utf-8")
    main(["burn", "add", "text", str(source)])
    capsys.readouterr()

    assert main(["burn", "run", "--yes"]) == int(Exit.OK)
    assert "success" in capsys.readouterr().out
    capsys.readouterr()
    main(["burn", "run"])
    assert "nothing" in capsys.readouterr().out.lower()


def test_orchestrate_runs_the_stages_and_saves_a_report(park, capsys, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    (repo / "file.txt").write_text("start\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "first"], cwd=repo, check=True)

    main(["scan"])
    main(["adapt"])
    capsys.readouterr()

    assert main(["orchestrate", "make it better", "--dir", str(repo)]) == int(Exit.OK)
    out = capsys.readouterr().out
    reports = list((park / "state" / "out").glob("*-orchestration.md"))
    assert reports, out
    assert str(reports[0]) in out, "путь до отчёта обязан быть назван"

    body = reports[0].read_text(encoding="utf-8")
    assert "make it better" in body
    for stage in ("spec", "work", "cross-review", "verdict"):
        assert stage in body, body


def test_orchestrate_review_comes_from_another_vendor(park, capsys, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    (repo / "file.txt").write_text("start\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "first"], cwd=repo, check=True)

    main(["scan"])
    main(["adapt"])
    capsys.readouterr()
    assert main(["--json", "orchestrate", "task", "--dir", str(repo)]) == int(Exit.OK)
    payload = json.loads(capsys.readouterr().out)
    assert payload["report"].endswith("-orchestration.md")
    stages = payload["stages"]
    work = next(s for s in stages if s["stage"] == "work")
    review = next(s for s in stages if s["stage"] == "cross-review")
    assert work["provider"] != review["provider"], stages


def test_orchestrate_without_roles_says_run_adapt(park, capsys, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    main(["scan"])
    capsys.readouterr()
    assert main(["orchestrate", "task", "--dir", str(repo)]) == int(Exit.NO_PROVIDER)
    assert "nn adapt" in capsys.readouterr().err

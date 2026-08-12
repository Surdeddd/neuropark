# Changelog

Release notes are kept in English, like commit messages. The product interface itself
speaks both English and Russian.
Заметки к релизам ведутся по-английски, как и коммиты. Сам интерфейс продукта
говорит и по-английски, и по-русски.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · versioning: [SemVer](https://semver.org/).

## 0.7.0 — 2026-08-12

Setup, presentation, and the localization the previous release only claimed.

### Added

- GitHub Actions CI: ubuntu and macOS × python 3.11, 3.12, 3.13. Beyond lint, types and
  unit tests it does a **cold start on a bare machine** (`init` → `scan` → `ls` → `doctor`
  against an empty `NN_HOME`) and checks that both languages answer.
- `SessionStart` hook for Claude Code. Silent by default; it speaks only when there is
  nothing to say otherwise — no catalog, never scanned, or a registry older than 30 days
  (which `nn` refuses to use).
- `hooks/pre-commit`: ruff, format check, mypy `--strict` and unit tests before a commit
  enters history. Install with `make hooks`; `install.sh` offers it. Skips itself when the
  tools are absent rather than blocking the commit.
- `make help` listing every target, plus `make hooks` and `make clean`.
- Issue templates, including one for adding a tool to `priors.json` — that path needs
  no code from you — and a pull request checklist.
- `CONTRIBUTING.md`.

### Fixed

- **English mode was answering in Russian.** `nn quota` printed `простаивает`, every
  validation error came out Russian, and so did park drift in `nn scan`. The old guard only
  watched literals inside `print` and `NnError`, so anything passed to a dataclass, a helper
  or a module constant slipped through. The guard now walks every literal in `src`, with a
  named exception for the refusal regexes that have to stay Russian to match Russian stderr.
- **The data layer had the same defect**, and no test looked there: `hosts/local.json` and
  `priors.json` carried the glued `english / русский` form, the recipe description and every
  dossier instruction were Russian-only. Human-facing fields now take `{en, ru}` through one
  shared parser, and `tests/test_data_bilingual.py` guards the bundled JSON — including
  halves accidentally swapped.
- **`nn ls <unknown>`, `nn doctor` and `nn stats` printed nothing at all** when there was
  nothing in the table. Silence is indistinguishable from a broken command; each now says
  what it found, and `ls` names the capabilities it does know.
- **Git's own environment could hijack a worktree run.** Inside any git hook, git exports
  `GIT_DIR`, `GIT_INDEX_FILE` and relatives; a child process with `cwd` set to a different
  repository still obeys those variables. So `nn orchestrate` called from a hook would have
  created the worktree and read the diff in the *caller's* repository. Found by the very
  first commit through the new pre-commit hook, which took 13 worktree tests down with it.
  Both `nn.worktree` and the local transport now scrub those variables (`nn.gitenv`), the
  hook unsets them too, and a test runs a worktree under a deliberately hostile `GIT_DIR`.
- The version in `pyproject.toml` had stayed at `0.1.0` while the CLI and the plugin
  manifest moved on. All three now come from one place and a test keeps them equal.
- `hooks/session-start.sh` no longer parses `ls` output; it globs.
- Exit code `8` covers a missing input file too — the README table said otherwise.

## 0.6.0 — 2026-08-12

### Added

- Layered catalog: your manifests in `$NN_HOME` override the bundled ones by `id`, so an
  update never clobbers your edits.
- `nn init`: detects installed tools from `priors.json` (14 tools) and writes manifests
  for them. `--dry-run` shows the table without writing.
- `examples/`: patterns for a script with its own interpreter, a tool on another machine,
  and an ssh host with a secret by reference.
- MIT license, `install.sh`, bilingual README pair.

### Fixed

- Quota was filtered before ranking, so an exhausted window silently handed work to the
  next provider. Quota is now checked after ranking: exit 6, the live alternative named,
  substitution only with `--fallback`.
- Exit codes no longer depend on the interface language — rejections carry a structured
  code instead of a human-readable reason.
- `detect.python` used the system interpreter, so providers with their own venv looked
  available until the first real failure.
- A dossier signature took the first stderr line, which is always `Traceback`; it takes
  the last one now.
- Absolute glob patterns went through `Path.glob`, which does not traverse the `/var`
  symlink on macOS: empty results after a ~20 second wait. One sanctioned entry point
  (`detect.glob_paths`) now expands every pattern, and a test forbids the old way.

## 0.5.0 — 2026-08-12

### Added

- Park drift reporting and packaging as a Claude Code plugin.
- Roles (`nn adapt`), orchestration through spec → work → cross-review → verdict, and
  isolated `git worktree` runs. Review always comes from a different vendor, and a patch
  is never applied.

## 0.4.0 — 2026-08-12

### Added

- Provider dossiers that fill themselves from the run log, with no LLM involved, and get
  injected into later prompts.

## 0.3.0 — 2026-08-12

### Added

- Quota windows computed from the run log, and `nn burn` for a window that would otherwise
  expire unused.

## 0.2.0 — 2026-08-12

### Added

- Manifests for a real park: 11 tools, 3 hosts, 2 bridges.

## 0.1.0 — 2026-08-12

### Added

- The catalog engine: scan, resolve with reasons, transports, type bridges, recipes,
  outcome classification and the run log.

# Changelog

Release notes are kept in English, like commit messages. The product interface itself
speaks both English and Russian.
Заметки к релизам ведутся по-английски, как и коммиты. Сам интерфейс продукта
говорит и по-английски, и по-русски.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · versioning: [SemVer](https://semver.org/).

## 0.10.0 — 2026-08-14

### Added

- **A recipe step can name a `role`.** The provider comes from that role's chain in
  `roles.json`, so the chain — not `rank` — decides the order, and the step falls through
  to the next provider when one is unavailable or its quota window is spent. This was the
  last documented gap in recipes. A live test proves the fall-through on real ffmpeg: the
  role names an uninstalled provider first, and the run lands on the second one despite it
  having the lower rank.
- `nn doctor` catches a recipe step pointing at a role that `roles.json` does not describe,
  before the run instead of during it.

### Changed

- The honest-gaps note names what is actually left: `adapter` providers for tools with a
  queue (ComfyUI), and with them the `http` host kind. A host reached over HTTP cannot run
  a shell command, so there is no generic "http transport" to write — the missing piece is
  the adapter, and it will be built against a real ComfyUI rather than a stub.

## 0.9.0 — 2026-08-13

### Fixed

- **The input check named the wrong cause.** A directory passed as input was reported as
  «not found», and a zero-byte file went to the tool and came back as its crash code (183
  from whisper) — a verdict about the model for a problem with the input. Each case says
  what it is now, and a relative input path is recorded absolute, because the provider's
  working directory is not always the current one.
- **Two runs in the same second shared one identity.** `run_id` was second-plus-provider,
  so two `nn run` of the same provider started within one second got the same output file,
  the same log and the same temp prefix, and clobbered each other — confirmed by two
  parallel whisper runs returning the identical `out`. Uniqueness inside a process now
  comes from a counter and between processes from a random token; a first attempt with two
  random bytes collided on 200 ids, which the test caught (birthday paradox). Orchestration
  ids had the same flaw and the same fix, where a collision meant a shared worktree.
- **`--out` into a directory that does not exist** produced outcome `empty` — a verdict
  about the model, when the truth was that nothing could be written. The parent directory
  is created, as it already was for default outputs.
- **A file name with a space broke the run.** Commands are assembled as shell strings, so
  `nn run transcribe "my clip.wav"` split into two arguments and died with exit 254 —
  and a name with a quote in it could have run whatever came after. Every path nn
  substitutes itself (`{in}` `{out}` `{out_base}` `{tmp}` `{dir}` `{prompt_file}`
  `{extraN}`) is now shell-escaped; `vars` and `host.paths.*` stay raw, because those
  are the manifest author's and may legitimately hold a set of flags.
- The same class in local detection: the interpreter pinned in `vars.py` and the `http`
  endpoint went into the shell unquoted, so a venv under «My Tools» or a URL with an
  ampersand broke the check — the ampersand would have pushed curl into the background
  and the answer would have been meaningless rather than wrong-but-honest.
- **ssh does not preserve argument boundaries** — it joins argv with spaces and hands the
  result to the remote login shell. So a remote path with a space was re-split over there:
  `cat -- '/tmp/…/итог (копия).txt'` failed on globbing, and worse, cleanup of
  `/tmp/my dir/nn-17` would have removed `/tmp/my` **and** `dir/nn-17`. Every remote call
  now sends one fully quoted command string.

- **A provider on a remote host was detected on the wrong machine.** Detection always ran
  locally, so `nn ls` answered about *this* computer: a binary in your own `PATH` made a
  provider on `gpu-box` look available, and its absence here marked a perfectly installed
  remote tool as missing. For an `ssh` host with `auto: true` every strategy now runs on
  that machine — `~` is its home, globs expand in its shell, `env` and `requires_key` are
  checked against the host's env, which is what the run will actually see. `version_cmd`
  goes there too.
- **An unreachable host was reported as a missing binary.** ssh failing to connect says
  nothing about the tool, so the status is `stale` with the real ssh error. `nn doctor` no
  longer asks "is the tool installed?" when the truth is that no host answered.
- **One broken manifest blinded the whole park.** An `NnError` from variable expansion (a
  `vars.py` pointing at an unset env variable, say) aborted the entire scan, leaving no
  registry at all. That provider is now `missing` with the error as its reason, and the rest
  of the park scans normally.

### Added

- Detection over ssh runs as **one connection per provider** instead of one per strategy:
  every check goes in a single script whose exit code names the first failure. On the loop
  it cut a four-strategy detect from 0.25s to 0.07s; over a real network the saving scales
  with the number of strategies.
- `nn doctor` warns about an `ssh` host that has no `PATH` in `env` (the top cause of a
  remote `command not found`) and about one with no `probe`.
- A live test for a **recipe with two inputs** — a step taking `{input}` and an earlier
  step's output at once — run through real ffmpeg, with ffprobe checking both streams
  landed. The README had been claiming multi-input recipes were unimplemented while
  `extra_in` worked; what is actually missing is a step naming a `role`.
- **`nn scan` probes in parallel** — hosts first, then providers, eight at a time. Detects
  wait on subprocesses and network rather than compute: npm and brew take about a second
  each, an unreachable host burns its whole connect timeout. Measured on a park with three
  dead hosts and four slow detects: 10.6s serial → 3.6s. Registry order still follows the
  catalog, not whoever answered first, so park drift stays meaningful.

## 0.8.0 — 2026-08-12

### Added

- **The ssh transport actually runs things.** A host with `kind: ssh` and `auto: true` no
  longer just prints a command: the input is sent to `paths.tmp`, the command runs in a
  per-run directory, the output (and any sibling the tool wrote next to it, which is how
  whisper behaves) comes back, and the directory is removed — whatever the outcome.
  - Files travel over the same ssh channel that runs the command, so nothing beyond `ssh`
    needs to exist on either side.
  - Secrets reach the command through the shell's environment, never through `argv` (visible
    in `ps` on the far side) and never as a file on the remote disk.
  - An unreachable host is a **recorded run** with outcome `crash`, not an exception — which
    is what lets dossiers learn from it.
  - `rm -rf` on the far side is guarded: it only fires for a path that ends in `/nn-<run_id>`
    with a non-empty run id.
- `ssh_options` in a host file for a one-off port, identity file or jump host. Permanent
  settings still belong in `~/.ssh/config`, so the field is optional.
- A dossier rule for `command not found`: on a remote host that almost always means the
  minimal `PATH` of a non-interactive ssh shell, not a missing tool.

### Fixed

- **Bridges ran on the provider's transport.** A bridge's availability is checked locally
  (`nn scan`, `nn doctor`), so running it on a remote machine tested nothing. Bridges are
  local now, and their output is staged like any other input.
- **A failed preparation left its directory behind.** When staging failed *after* the remote
  directory was created, nothing cleaned it up — found by a live run that left `nn-…` dirs on
  the far side.

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
- **`nn doctor` called a bare machine broken.** With no tool installed, every capability
  produced a `error … no available provider` and doctor exited 7 — so the first thing a new
  user saw after `install.sh` looked like nn itself was broken. An unavailable provider is
  now a warning with a question ("is the tool installed?"), and the exit code stays 0. Real
  catalog defects — a bad template, a moved model path, a role pointing at nothing — are
  still errors. Caught by the CI step written in this same release.
- **The launcher died with a raw `ImportError` on old python.** `bin/nn` ran whatever
  `python3` came first, and on macOS that is often the system 3.9, which fails on
  `datetime.UTC`. It now looks for a 3.11+ interpreter and, failing that, says so in one
  line and exits 7. `NN_PYTHON` overrides the search and is authoritative: a named
  interpreter that cannot run nn is refused by name, never silently swapped — the same rule
  providers live by. The check compares the interpreter's answer, not its exit status, so
  `/bin/echo` can no longer pose as python.
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

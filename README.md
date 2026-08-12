<div align="center">

# nn

**One catalog for every AI tool you own. One command to call any of them.**

[![ci](https://github.com/Surdeddd/neuropark/actions/workflows/ci.yml/badge.svg)](https://github.com/Surdeddd/neuropark/actions/workflows/ci.yml)
[![python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![deps](https://img.shields.io/badge/runtime%20deps-zero-brightgreen)](#why-it-stays-alive)
[![typed](https://img.shields.io/badge/mypy-strict-blue)](#development)
[![license](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)
[![lang](https://img.shields.io/badge/UI-EN%20%2F%20RU-orange)](#language)

[Quick start](#quick-start) · [How it works](#how-it-works) · [Add a tool](#add-a-tool) · [Chains](#chains) · [Orchestration](#orchestration) · [Русская версия](README.ru.md)

</div>

---

Your AI tools drift apart. Whisper models in three folders, an MLX voice model, ComfyUI on the box under the desk, four agent CLIs on subscriptions, a cloud image generator, an embedder. The knowledge of *what does this, where it lives, which flags it takes* stays in your head — and every new pipeline gets wired by hand again.

`nn` turns that scattered pile into a catalog with one calling contract.

```bash
nn ls                          # what do I actually have
nn why transcribe --in-type video   # who gets picked, and why the others don't
nn run transcribe talk.mp4     # → subtitles. The audio bridge inserts itself
nn run tts script.txt          # → voice
nn recipe run bilingual-subs clip.mp4   # transcript → translate → burn-in, one command
```

## Quick start

```bash
git clone https://github.com/Surdeddd/neuropark.git
cd neuropark && ./install.sh
```

That's the whole setup. `install.sh` checks python, links the Claude Code skill, then **finds your tools by itself** and writes manifests for them:

```
tool                  capability     state    model / reason
--------------------  -------------  -------  ------------------------------------
whisper-cpp           transcribe     found    ~/Models/whisper/ggml-large-v3.bin
ffmpeg-audio-clean    audio-clean    found    ~/Models/rnnoise/sh.rnnn
ffmpeg-compose        compose        found    -
claude-text           text           found    -
codex-text            text           found    -
ollama                text           absent   no ollama
comfyui               image          absent   endpoint did not answer

written manifests: 10
```

Nothing to configure by hand to get started. Runtime needs **python 3.11+ and nothing else** — no pip install, no dependencies.

<details>
<summary><b>What the installer does, and how to skip parts of it</b></summary>

| step | what happens | how to opt out |
|---|---|---|
| 1 | checks python 3.11+, makes `bin/nn` executable | — |
| 2 | links `skills/nn` into `~/.claude/skills/nn` so Claude Code can reach it | remove the symlink |
| 3 | tells you the `PATH` line to add — never edits your shell profile | — |
| 4 | offers the git pre-commit hook (lint, types, tests) | answer `N`; add later with `make hooks` |
| 5 | `nn init` + `nn scan` — detects your tools and writes the registry | — |

Non-interactive install: `NN_INSTALL_HOOKS=1 ./install.sh` takes the hook without asking,
and without a TTY the hook is simply skipped. Re-running the installer is safe: an existing
symlink and an existing hook are left alone.

```bash
export NN_HOME=~/my-park       # where your manifests live (default ~/.claude/nn/data)
export NN_STATE=~/my-park-state  # registry, run log, dossiers (default ~/.claude/nn)
export NN_LANG=ru              # interface language
```

</details>

<details>
<summary><b>As a Claude Code plugin</b></summary>

```
/plugin marketplace add Surdeddd/neuropark
/plugin install neuropark
```

You get the `nn` skill, the `/nn` command, and a `SessionStart` hook that stays silent
unless the park needs attention — no catalog yet, never scanned, or a registry old enough
that `nn` refuses to use it. Then it prints one line naming the command that fixes it.

</details>

## How it works

```
    you ──▶ nn run transcribe video.mp4
                    │
                    ▼
            ┌───────────────┐   capability → provider, with reasons
            │   resolver    │   filters: available? right OS? quota left?
            └───────┬───────┘   ranks:   rank → local first → recent success
                    │
              type mismatch?
                    │  video ≠ audio
                    ▼
            ┌───────────────┐
            │    bridge     │   ffmpeg -vn  →  16k mono wav
            └───────┬───────┘
                    ▼
            ┌───────────────┐   local · ssh (stages files) · manual (prints it)
            │  transport    │
            └───────┬───────┘
                    ▼
            ┌───────────────┐   success · empty · timeout · quota · refused · crash
            │   outcome     │   exit 0 alone is never proof of success
            └───────┬───────┘
                    ▼
        envelope (JSON) + run log + auto-filled dossier
```

Three layers, and only the middle one is code:

| layer | what lives there | who edits it |
|---|---|---|
| **data** | `providers/` `hosts/` `bridges/` `recipes/` `roles.json` `capabilities.json` | you, with a text editor |
| **engine** | resolve · bridge · transport · quota · dossier · orchestrate | 34 modules, stdlib only |
| **state** | registry, run log, quota windows, dossiers, patches | written by `nn`, never by hand |

The engine holds **no list** of tools, machines or capabilities. All of that is data — which is why adding a tool costs one file, not a pull request.

## Add a tool

One JSON file, and the file name must match the `id`:

```json
{
  "id": "whisper-cpp",
  "capability": "transcribe",
  "kind": "model",
  "rank": 10,
  "detect": { "bin": "whisper-cli", "files": ["~/Models/whisper/ggml-large-v3.bin"] },
  "vars":   { "model": "~/Models/whisper/ggml-large-v3.bin" },
  "io":     { "in": ["audio"], "out": "srt" },
  "pre":    "ffmpeg -nostdin -y -i {in} -ar 16000 -ac 1 {tmp}.wav",
  "run":    "whisper-cli -m {model} -f {tmp}.wav -osrt -of {out_base} -l auto",
  "notes":  { "en": "most accurate locally, ~2× slower than turbo",
              "ru": "самый точный локально, примерно вдвое медленнее turbo" }
}
```

Drop it in `$NN_HOME/providers/` (default `~/.claude/nn/data/providers/`) and run `nn scan`. Your files **override** the bundled ones with the same `id`, so nothing you write gets clobbered by an update.

<details>
<summary><b>Every field, and the nine ways to detect a tool</b></summary>

| field | meaning |
|---|---|
| `capability` | what it does. One tool with two skills = two manifests |
| `kind` | `model` · `tool` · `agent` |
| `host` | host id, `local` by default |
| `rank` | higher wins among available providers |
| `detect` | how to check presence — see below. All conditions are ANDed |
| `requires_key` | env vars; missing ones give status `needs-key`, not "no such tool" |
| `io.in` / `io.out` | type classes from `capabilities.json`. `out: "same"` preserves the input type |
| `io.out_ext` | when the tool writes a different container than the type's default extension |
| `vars` | template substitutions; `~` and `$ENV` are expanded |
| `pre` / `run` / `post` | command templates, with per-OS variants: `{"darwin": "…", "linux": "…"}` |
| `timeout_s` | default 900 |
| `window_h`, `soft_cap_calls` | quota window length and soft call cap |
| `quota_patterns` | stderr regexes that mean the window is exhausted |
| `vendor` | for orchestration: review must come from another vendor |
| `notes` | **required**, bilingual `{en, ru}`: speed, quality, known gotchas |

Detection strategies: `bin` · `files` · `glob` · `env` · `http` · `python` · `npm` · `docker` · `brew`.

Template variables: `{in}` `{out}` `{out_base}` `{tmp}` `{dir}` `{prompt_file}` `{extra0}` `{host.paths.key}` plus everything from `vars`. An unknown variable is a validation error, never a silent empty string.

Ready-made patterns live in [`examples/`](examples/): a script needing its own interpreter, a tool on another machine, an ssh host with a secret by reference.

</details>

<details>
<summary><b>Add a machine</b></summary>

```json
{ "id": "gpu-box", "kind": "ssh", "addr": "gpu-box", "auto": true,
  "probe": "ssh -o ConnectTimeout=3 -o BatchMode=yes gpu-box true",
  "paths": { "models": "/data/models", "tmp": "/var/tmp" },
  "env": { "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin" } }
```

`kind`: `local` · `ssh` · `http` · `manual`. **`auto: false` means `nn` prints the ready command instead of running it** — useful for a machine you'd rather drive by hand, and the only mode `http` has.

**A remote run with `auto: true`** sends the input to `paths.tmp` (default `/tmp`), runs the command in a per-run directory, brings the output back, and removes that directory — whatever the outcome. Files travel over the same ssh channel that runs the command, so nothing beyond `ssh` has to be installed. A host that is asleep or unreachable becomes a recorded run with outcome `crash`, not a stack trace.

> **Set `env.PATH`.** A non-interactive ssh shell has a minimal `PATH` and does not see `/opt/homebrew/bin` or `/usr/local/bin`. Without it, a tool that *is* installed still reports `command not found` — nn's dossier will tell you so, but it costs a run to find out.

Port, identity file and jump host belong in `~/.ssh/config` (`addr` is then just the alias); `"ssh_options": ["-p", "2222"]` is there for the one-off case. `BatchMode` is always on, so nn never hangs on a password prompt.

Secrets go in only by reference: `"KEY": "@file:~/.config/secrets/k"`. Read at run time, never committed — and on a remote run they reach the command through the shell's environment, never through `argv` (visible in `ps` on the far side) and never as a file on the remote disk.

</details>

## Chains

A recipe is data. The output of step N is the input of N+1, and a type mismatch gets a bridge inserted automatically:

```json
{ "id": "bilingual-subs",
  "steps": [
    { "capability": "transcribe" },
    { "capability": "translate", "vars": { "lang": "ru" } },
    { "capability": "subtitle-burn", "in": "{input}", "extra_in": ["{step1.out}"] }
  ] }
```

```bash
nn recipe run bilingual-subs clip.mp4
```

`{input}` is the recipe's original input, `{stepK.out}` the output of step K. Forward references are rejected at validation time.

## Orchestration

For work that deserves more than one model:

```bash
nn adapt                                   # lay your text CLIs out across roles, once
nn orchestrate "fix the parser" --dir .     # spec → work → cross-review → verdict
nn orchestrate "…" --fanout 3               # three attempts, each in its own worktree
```

Two guarantees, both covered by tests:

- **Review comes from a different vendor** than the patch author. No model reviews itself.
- **A patch is never applied.** Work happens in an isolated `git worktree` off HEAD; you get a `.patch` file. Merging is your call. A repository mid-rebase is refused before the worktree is created.

## Quotas and dossiers

Both fill themselves from the run log — nothing to maintain by hand.

```bash
nn quota          # windows: burned, idle, when they close
nn burn add image prompt.txt && nn burn run --yes   # spend a window that would expire unused
nn learn          # distil failures into provider dossiers
```

A dossier is what the catalog learned the hard way, assembled with no LLM involved:

```
## observed
- «modulenotfounderror: no module named mlx_audio» × 3, last seen 2026-08-12T10:00

## instructions
- this provider needs its own interpreter: check vars.py, the system python won't do
```

That instruction is injected into the provider's prompt from then on. Turn it off per call with `--no-dossier`.

## Two rules the engine never breaks

> **No silent model substitution.** If the best provider's window is exhausted, `nn` fails with exit code 6, names the live alternative and waits for `--fallback`. Substitution happens only when you asked for it.

> **Nothing is applied automatically.** Patches aren't merged, `auto: false` hosts print the command, the scan only reads, `burn` without `--yes` only proposes.

## Language

The whole interface speaks English and Russian. `NN_LANG=en` or `NN_LANG=ru`; without it the language follows `LC_ALL`/`LANG`, falling back to English. Command help, messages, table headers and tool notes all switch.

## Exit codes

Made for scripts and agents, not just for humans:

| code | meaning |
|---|---|
| `0` | success |
| `2` | no available provider for the capability |
| `3` | manual run required — the command was printed |
| `4` | the provider failed |
| `5` | no registry, or older than 30 days → run `nn scan` |
| `6` | quota window exhausted |
| `7` | invalid manifest, template or recipe |
| `8` | input problem: file missing, unsupported type with no bridge, or a required `--extra` absent |

Outcome classes in every envelope: `success` `empty` `timeout` `quota` `refused` `crash`. An empty file or a reply like *"Ready to work. What's the task?"* is classified `empty`, not success.

## Catalog freshness

You run the scan: `nn scan`. There are deliberately **no schedules, daemons or notifications** — less infrastructure, fewer things to rot. The scan reports what changed since last time:

```
changes since last scan
appeared:
  ollama — new tool, status ok
disappeared:
  kimi-text — manifest is gone from the catalog
```

## Why it stays alive

`nn` replaced two earlier attempts of mine that died: they collected 4 invocations in a month and their model dossiers stayed empty forever. The postmortem shaped this design:

| what killed them | what changed |
|---|---|
| required hand-seeding configs and dossiers | quotas and dossiers compute themselves from the run log |
| carried complexity before it paid off | six phases, each verified on real hardware before the next |
| never got called — no explicit triggers | the skill description lists when to reach for it, in both languages |
| no way to see what was unused | `nn stats` — a feature with zero calls for a month gets deleted, not finished |

## Development

```bash
make help         # every target
make check        # ruff + ruff format + mypy --strict + 382 unit tests, no network, ~10s
make smoke-fast   # live offline runs: scan, transcript, bridge, doctor (~30s)
make smoke        # plus TTS with a cold model start (up to 15 min)
make hooks        # git pre-commit hook: the same checks before anything enters history
```

CI runs `make check` on ubuntu and macOS across python 3.11, 3.12 and 3.13, then does a
**cold start on a bare machine** — `init` → `scan` → `ls` → `doctor` against an empty
`NN_HOME`, where almost no tool exists — and checks that both languages answer.

Rules that hold: stdlib only at runtime · no `type: ignore` anywhere in `src` · tests never touch the network or spend a subscription · all human-facing text bilingual via `nn.i18n.bi`.

Adding a tool needs no code from you — see [CONTRIBUTING.md](CONTRIBUTING.md). Release notes: [CHANGELOG.md](CHANGELOG.md).

Not implemented, and saying so instead of failing silently: the `http` transport (such hosts print the command), `adapter` providers for tools that need a queue, recipes with multiple inputs.

## License

MIT — see [LICENSE](LICENSE).

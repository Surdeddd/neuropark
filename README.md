# nn — neural park catalog and a single calling contract

**Русская версия: [README.ru.md](README.ru.md)**

A neural park drifts across machines and runtimes: five agent CLIs, whisper models in three different folders, MLX models, ComfyUI on another box, cloud generators, a local TTS, an embedder. The knowledge of "what does this, where it lives, which flags it takes" lives in someone's head, and every new chain gets wired by hand again.

`nn` does two things:

1. **Park analysis** — one registry of every neural tool on every machine: what exists, where, whether it is alive, how it differs from its neighbour for the same job. `nn ls` shows the park, `nn why` explains which provider was picked and why the others were rejected.
2. **Fast integration** — a single calling contract: `nn run <capability> <file>`. The output of one step feeds the next, type mismatches are closed by a bridge automatically, and chains are described by JSON recipes.

The core principle: **universality through data, not code**. The engine holds no list of tools, machines or capabilities — all of that is files. Adding a tool is one manifest file. Adding a machine is one host file. A new scenario is one recipe file.

## Installation

```bash
git clone <repo> ~/Projects/Personal/neuropark
cd ~/Projects/Personal/neuropark && ./install.sh
```

`install.sh` is idempotent: it checks python, symlinks the skill into `~/.claude/skills/nn`, prints the PATH line to add, and runs the first park scan. As a Claude Code plugin it installs through the marketplace manifest in `.claude-plugin/`, which also gives you the `/nn` slash command.

Runtime needs python 3.11+ from stdlib only — zero external dependencies. Dev tools (pytest, ruff, mypy) are separate; `make check` pulls pytest through `uv`.

## Language

The product speaks both English and Russian. Pick with `NN_LANG=en` or `NN_LANG=ru`; without it the language follows `LC_ALL`/`LANG`, falling back to English. This covers command help, messages, table headers and provider notes.

## Quick start

```bash
nn scan                                   # probe detectors, write the registry
nn ls                                     # the whole park as a table
nn ls transcribe                          # a single capability
nn why transcribe --in-type video         # who was picked, who was rejected and why
nn run transcribe video.mp4               # video → subtitles (bridge inserts itself)
nn run tts text.txt                       # text → voice
nn run image prompt.txt -o poster.png     # prompt → picture
nn recipe ls                              # ready-made chains
nn recipe run bilingual-subs clip.mp4     # transcript → translation → burned-in subs
nn quota                                  # quota windows: burned, idle
nn burn add image prompt.txt              # queue work for a free window
nn burn run                               # show what can be burned (--yes to execute)
nn adapt                                  # build roles.json for this machine
nn orchestrate "fix the parser" --dir .   # spec → work in a worktree → review → verdict
nn learn                                  # distil run outcomes into provider dossiers
nn doctor                                 # what is broken in the catalog
nn stats                                  # what actually gets used
```

Every `nn run` prints a JSON envelope: provider, host, output file, bridge, duration, outcome class, log path. `--json` on `ls`/`why` gives machine-readable output for agents.

## Adding a neural tool

One file in `providers/<id>.json`, where `<id>` matches the file name:

```json
{
  "id": "whisper-cpp-large-v3",
  "capability": "transcribe",
  "kind": "model",
  "rank": 10,
  "detect": { "bin": "whisper-cli", "files": ["~/Models/whisper/ggml-large-v3.bin"] },
  "vars": { "model": "~/Models/whisper/ggml-large-v3.bin" },
  "io": { "in": ["audio"], "out": "srt" },
  "pre": "ffmpeg -nostdin -y -i {in} -ar 16000 -ac 1 {tmp}.wav",
  "run": "whisper-cli -m {model} -f {tmp}.wav -osrt -of {out_base} -l auto",
  "timeout_s": 3600,
  "notes": {
    "en": "most accurate locally, roughly twice slower than turbo",
    "ru": "самый точный локально, примерно вдвое медленнее turbo"
  }
}
```

| field | meaning |
|---|---|
| `capability` | what it does. One tool with two skills means two manifests |
| `kind` | `model` \| `tool` \| `agent` |
| `host` | host id, `local` by default |
| `rank` | higher wins among available providers |
| `detect` | how to check presence: `bin`, `files`, `glob`, `env`, `http`, `python`, `npm`, `docker`, `brew`. All conditions are ANDed |
| `requires_key` | env variables; missing ones give status `needs-key`, not "no such tool" |
| `io.in` / `io.out` | type classes from `capabilities.json`. `out: "same"` preserves the input type |
| `io.out_ext` | when the provider writes something other than the class's first extension (ben-voice always encodes opus → `ogg`) |
| `vars` | template substitutions; `~` and `$ENV` are expanded |
| `pre` / `run` / `post` | command templates. Per-OS variants allowed: `"run": {"darwin": "...", "linux": "..."}` |
| `quota_patterns` | stderr regexes that mean the window is exhausted |
| `notes` | required, bilingual `{en, ru}`: speed, quality, known gotchas |

Template variables: `{in}`, `{out}`, `{out_base}`, `{tmp}`, `{dir}`, `{prompt_file}`, `{extra0}`, `{host.paths.<key>}` plus everything from `vars`. An unknown variable is a validation error, not an empty substitution.

Three live examples ship with the repo: a local binary (`whisper-cpp-large-v3`), a python script with its own interpreter (`ben-voice-clone`), and a remote declaration that is never executed (`comfy-zimage`).

## Adding a machine

`hosts/<id>.json`:

```json
{ "id": "winpc", "kind": "ssh", "addr": "winpc-cc", "os": "windows", "auto": false,
  "probe": "ssh -o ConnectTimeout=3 -o BatchMode=yes winpc-cc true",
  "paths": { "comfy": "http://127.0.0.1:8188" },
  "notes": "falls asleep mid-job" }
```

`kind`: `local` · `ssh` · `http` · `manual`. **`auto: false` means `nn` prints the ready command but never runs it** — that is how remote tools stay in the catalog and in `why` without dragging in the whole class of sleep-and-network bugs.

Secrets in host files are allowed only by reference: `"ANTHROPIC_API_KEY": "@file:~/.config/secrets/key"`. The value is read at run time and never lands in git.

## Adding a scenario

`recipes/<id>.json`. A step names a `capability`; the output of step N becomes the input of N+1:

```json
{ "id": "bilingual-subs",
  "description": "video → transcript → translation → burned-in subtitles",
  "steps": [
    { "capability": "transcribe" },
    { "capability": "translate", "vars": { "lang": "ru" } },
    { "capability": "subtitle-burn", "in": "{input}", "extra_in": ["{step1.out}"] }
  ],
  "on_quota": "fail" }
```

References: `{input}` is the recipe's original input, `{stepK.out}` is the output of step K (zero-indexed, forward references are rejected). `extra_in` feeds capabilities that need two files, like burning subtitles or swapping an audio track. `on_quota` is `fail` (default) or `fallback`.

## Exit codes

| code | meaning |
|---|---|
| `0` | success |
| `2` | no available provider for the capability |
| `3` | manual run required, the command was printed |
| `4` | the provider failed |
| `5` | no registry, or it is older than 30 days — run `nn scan` |
| `6` | quota window exhausted |
| `7` | invalid manifest, template or recipe |
| `8` | input type unsupported and no bridge, or a required `--extra` is missing |

Outcome classes in the envelope and the run log: `success` · `empty` · `timeout` · `quota` · `refused` · `crash`. `exit 0` alone is not proof of success — an empty file or a reply like "Ready to work. What's the task?" is classified as `empty`.

## Quotas

Nothing to fill in by hand: `quota.json` is computed entirely from `runs.jsonl`. A manifest declares `window_h` (rolling window length) and optionally `soft_cap_calls`. Exhaustion is detected two ways — the counter reaches `soft_cap_calls`, or a run inside the window had outcome `quota` (recognised by `quota_patterns` in stderr), which closes the window until its end.

`window_h` is only set where the window length is a known fact (Anthropic and ChatGPT subscriptions are 5 hours). It is deliberately empty for Grok Imagine: a made-up number would lie in `nn quota` reports.

`nn burn` takes windows about to close unused, matches them against the `burn-queue.jsonl` queue and shows a proposal. Nothing runs without `--yes`.

## Provider dossiers

They fill themselves — the key difference from the predecessor, whose dossiers stayed empty because they required manual seeding.

The engine reads new `runs.jsonl` lines from a watermark and distils failures into lessons with no LLM involved: three empty answers on one capability, two timeouts, three repeats of one error signature (the first stderr line stripped of numbers and paths — for a python traceback the last line is taken, because that is where the meaning is). A ready instruction is emitted only when the signature matches a known rule from `dossier-rules.json`; everything else is recorded as a fact with a counter and a date, without invented advice.

A dossier lives in `~/.claude/nn/dossiers/<provider>.md` with two sections: `observed` (facts) and `instructions` (imperatives). Capped at 40 lines, oldest observations evicted. Only `instructions` is injected into prompts; `--no-dossier` turns that off. `nn learn` runs by hand, and fires automatically after 20 new records.

A real example the engine assembled from live failures:

```
## observed
- «modulenotfounderror: no module named mlx_audio» × 3, последний раз 2026-08-12T10:00

## instructions
- у провайдера свой интерпретатор: проверь vars.py в манифесте, системный python не годится
```

## Orchestration

`nn adapt` distributes available text providers across roles — deterministically, from scan results and `roles` hints in manifests, with no LLM. The file lands in `~/.claude/nn/roles.json` and is meant to be hand-edited: the order in `providers` is the role's fallback chain.

`nn orchestrate "<task>"` drives the task through stages. Stage-to-role mapping is fixed: `spec` → role `spec`, `work` → `mechanics` (or `--role frontend`), `cross-review` → `review`, `verdict` → `core`. The route is deterministic; LLMs only work inside providers.

Two guarantees:

- **Review goes to a different vendor** than the patch author — no model reviews itself. The vendor comes from the `vendor` field or the `id` prefix.
- **A patch is never applied.** A role with `worktree: true` works in an isolated `git worktree` off HEAD and hands back a `.patch` file. Merging is your decision. A repository mid-rebase or mid-merge is rejected before the worktree is created.

`--fanout N` runs N workers on one task in separate worktrees, each with its own patch — review and verdict see all of them.

Patches are written with `core.quotePath=false` so non-ASCII file names stay readable instead of turning into octal escapes.

## Catalog freshness

The human runs the scan: `nn scan`. There are deliberately no schedules, background jobs or messenger notifications — less infrastructure, fewer things to rot.

The scan itself reports what changed since last time: which tool appeared, which disappeared, whose status changed or version moved. The first scan does not count as drift. If the registry is older than 30 days, any command reminds you with exit code 5.

## Two rules the engine never breaks

- **No silent model substitution.** If the best provider's window is exhausted, `nn` does not quietly take the next one: it fails with code 6, names the live alternative and suggests `--fallback`. Substitution happens only when you asked for it.
- **Nothing is applied automatically.** A host with `auto: false` prints the command, patches are not merged, the scan only reads, and `burn` without `--yes` only proposes.

## Development

```bash
make check        # ruff + mypy --strict + unit tests, no network, ~10 seconds
make smoke-fast   # live offline runs: scan, transcript, bridge, doctor (~30 seconds)
make smoke        # plus TTS with a cold MLX start (up to 15 minutes)
```

The full `bilingual-subs` chain is not in the automated suite: its third step calls `claude -p` and spends a subscription. Verify it by hand or through the fake providers in `tests/test_integration_chain.py`.

## What is next

All six phases are closed: core, type stitching, quotas, dossiers, orchestration, packaging. Deliberately not implemented, and saying so explicitly instead of failing silently:

- `ssh` and `http` transports — remote hosts work through `auto: false`, i.e. they print the command. Wire them when copying that command by hand gets old.
- providers with an `adapter` script instead of a template — needed for ComfyUI with a queue and status polling.
- recipes with multiple inputs and `role` steps inside recipes.

Whether any of that is actually needed should be judged by `nn stats`: a feature with zero calls for a month gets deleted, not finished.

Spec: `docs/superpowers/specs/2026-08-12-nn-design.md`. Phase 1–2 plan: `docs/superpowers/plans/2026-08-12-nn-phases-1-2.md`.

#!/usr/bin/env bash
# nn setup: check python, link the Claude skill, detect your tools, scan the park.
# Установка nn: проверка python, подключение скилла, поиск инструментов, скан парка.
# Idempotent — safe to re-run. / Идемпотентно — можно гонять повторно.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
skills_dir="${HOME}/.claude/skills"
link="${skills_dir}/nn"

say() { printf '%s\n' "$*"; }

say "nn setup — ${root}"
say

if ! command -v python3 >/dev/null 2>&1; then
  say "python3 3.11+ required but not found / нужен python3 3.11+, но его нет" >&2
  exit 1
fi
python3 - "$@" <<'PY'
import sys
if sys.version_info < (3, 11):
    sys.exit(f"python 3.11+ required, found {sys.version.split()[0]}")
PY

chmod +x "${root}/bin/nn"
say "1/4  python ok, bin/nn executable"

if [ -L "${link}" ] || [ -e "${link}" ]; then
  say "2/4  Claude skill already linked: ${link}"
else
  mkdir -p "${skills_dir}"
  ln -s "${root}/skills/nn" "${link}"
  say "2/4  Claude skill linked: ${link}"
fi

case ":${PATH}:" in
  *":${root}/bin:"*) say "3/5  bin already in PATH" ;;
  *) say "3/5  add to your shell profile:  export PATH=\"${root}/bin:\$PATH\"" ;;
esac

# The git hook is offered, never forced: it belongs to whoever commits here.
# Гит-хук предлагается, а не навязывается: он принадлежит тому, кто тут коммитит.
if [ -d "${root}/.git" ] && [ ! -e "${root}/.git/hooks/pre-commit" ]; then
  if [ "${NN_INSTALL_HOOKS:-}" = "1" ]; then
    reply=y
  elif [ -t 0 ]; then
    printf '4/5  install the git pre-commit hook (lint, types, tests)? [y/N] '
    read -r reply || reply=n
  else
    reply=n
  fi
  case "${reply}" in
    y | Y) ln -sf ../../hooks/pre-commit "${root}/.git/hooks/pre-commit" && say "     hook installed → hooks/pre-commit  (skip once: git commit --no-verify)" ;;
    *) say "     skipped — install later with:  make hooks" ;;
  esac
else
  say "4/5  git pre-commit hook: nothing to do"
fi

say
say "5/5  detecting your tools / ищу твои инструменты"
say
"${root}/bin/nn" init
say
"${root}/bin/nn" scan

say
say "done. next:  nn ls  ·  nn why transcribe  ·  nn run transcribe file.mp4"
say "language:    NN_LANG=en or NN_LANG=ru"
say "your data:   \${NN_HOME:-~/.claude/nn/data}  (edit manifests there, they win over bundled)"
say "the scan is manual on purpose: no schedules, no daemons, no notifications"

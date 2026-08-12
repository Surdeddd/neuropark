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
  *":${root}/bin:"*) say "3/4  bin already in PATH" ;;
  *) say "3/4  add to your shell profile:  export PATH=\"${root}/bin:\$PATH\"" ;;
esac

say
say "4/4  detecting your tools / ищу твои инструменты"
say
"${root}/bin/nn" init
say
"${root}/bin/nn" scan

say
say "done. next:  nn ls  ·  nn why transcribe  ·  nn run transcribe file.mp4"
say "language:    NN_LANG=en or NN_LANG=ru"
say "your data:   \${NN_HOME:-~/.claude/nn/data}  (edit manifests there, they win over bundled)"
say "the scan is manual on purpose: no schedules, no daemons, no notifications"

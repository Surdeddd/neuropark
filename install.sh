#!/usr/bin/env bash
# Установка nn: симлинк скилла в ~/.claude/skills и первый скан парка.
# Идемпотентно — можно гонять повторно.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
skills_dir="${HOME}/.claude/skills"
link="${skills_dir}/nn"

echo "корень: ${root}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "нужен python3 3.11+ — не найден" >&2
  exit 1
fi
python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    sys.exit(f"нужен python 3.11+, а есть {sys.version.split()[0]}")
PY

mkdir -p "${skills_dir}"
if [ -L "${link}" ] || [ -e "${link}" ]; then
  echo "скилл уже подключён: ${link}"
else
  ln -s "${root}/skills/nn" "${link}"
  echo "скилл подключён: ${link} → ${root}/skills/nn"
fi

chmod +x "${root}/bin/nn"

case ":${PATH}:" in
  *":${root}/bin:"*) echo "bin уже в PATH" ;;
  *) echo "добавь в шелл-профиль:  export PATH=\"${root}/bin:\$PATH\"" ;;
esac

echo
echo "первый скан парка:"
"${root}/bin/nn" scan

echo
echo "готово. дальше: nn ls · nn why <capability> · nn run <capability> <файл>"
echo "скан запускается только руками — расписаний и фоновых заданий тут нет"

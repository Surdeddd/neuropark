#!/usr/bin/env bash
# SessionStart hook: says something ONLY when nn needs attention.
# Хук SessionStart: подаёт голос ТОЛЬКО когда nn требует внимания.
#
# stdout of this hook becomes context Claude can see, so silence is the default:
# a hook that greets you every session is noise, and noise gets ignored.
# stdout попадает в контекст Клоду, поэтому по умолчанию тишина: хук, который
# здоровается каждую сессию, — это шум, а шум перестают читать.
set -uo pipefail

state="${NN_STATE:-$HOME/.claude/nn}"
data="${NN_HOME:-$state/data}"

# Pure globbing, no ls: the output of ls is not a contract.
registry=""
for candidate in "$state"/registry.*.json; do
  [ -f "$candidate" ] && registry="$candidate" && break
done

manifests=""
for candidate in "$data"/providers/*.json; do
  [ -f "$candidate" ] && manifests="yes" && break
done

# No catalog at all: nothing was ever set up.
if [ -z "$manifests" ]; then
  echo "nn: no personal catalog yet. Run 'nn init' to detect installed AI tools, then 'nn scan'."
  exit 0
fi

# Never scanned.
if [ -z "$registry" ]; then
  echo "nn: the park was never scanned. Run 'nn scan' before using nn (commands would exit 5)."
  exit 0
fi

# Scanned, but the registry is older than 30 days — nn refuses to use it.
if [ -n "$(find "$registry" -mtime +30 2>/dev/null)" ]; then
  age="$(( ( $(date +%s) - $(stat -f %m "$registry" 2>/dev/null || stat -c %Y "$registry") ) / 86400 ))"
  echo "nn: the registry is ${age} days old and nn treats it as stale (exit code 5). Run 'nn scan'."
  exit 0
fi

exit 0

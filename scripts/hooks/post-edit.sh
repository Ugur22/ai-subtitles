#!/bin/bash
# Claude Code PostToolUse hook (Edit|Write): fast lint after code edits.
# Exit 2 sends the failure back to the agent so it fixes it before moving on.
set -u

file=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))' 2>/dev/null)

case "$file" in
  *.py|*.ts|*.tsx|*.js|*.jsx) ;;
  *) exit 0 ;;
esac

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}" || exit 0

if ! out=$(make check-fast 2>&1); then
  echo "make check-fast failed after editing $file:" >&2
  echo "$out" | tail -40 >&2
  exit 2
fi

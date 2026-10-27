#!/bin/bash
# Claude Code Stop hook: refuse to finish while `make check` is red.
# Exit 2 blocks the stop and feeds the output back to the agent.
set -u

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}" || exit 0

# Nothing code-related changed, so there is nothing new to verify.
if [ -z "$(git status --porcelain -- 'backend/*.py' 'frontend/src' 'frontend/package.json' 'Makefile' 2>/dev/null)" ]; then
  exit 0
fi

# Cap consecutive blocks so a check the agent can't fix never traps the session.
counter="${TMPDIR:-/tmp}/ai-subs-stop-blocks"
blocks=$(cat "$counter" 2>/dev/null || echo 0)

if out=$(make check 2>&1); then
  rm -f "$counter"
  exit 0
fi

if [ "$blocks" -ge 3 ]; then
  rm -f "$counter"
  echo "make check still failing after 3 blocked stops; letting the session end. Report the failure to the user." >&2
  exit 0
fi

echo $((blocks + 1)) > "$counter"
echo "make check failed; fix before finishing:" >&2
echo "$out" | tail -60 >&2
exit 2

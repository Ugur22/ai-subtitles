#!/bin/bash
# Kill stale Claude Code background subagent processes
# These are spawned by Claude Code IDE integrations and accumulate over time
#
# Usage:
#   ./scripts/kill-stale-claude.sh          # dry run (show what would be killed)
#   ./scripts/kill-stale-claude.sh --kill    # actually kill them

set -euo pipefail

MODE="${1:-dry-run}"

# Get current interactive claude sessions (attached to a terminal)
# We want to preserve these - they're your active sessions
INTERACTIVE_PIDS=$(ps aux | grep "[c]laude" | awk '$7 ~ /s[0-9]+/ && $7 ~ /\+/ {print $2}' | sort -u)

# Get all background subagent processes (stream-json flag = spawned by IDE)
STALE_PIDS=$(ps aux | grep "[c]laude.*stream-json" | awk '{print $2}')

# Filter out any that match interactive PIDs
KILL_PIDS=""
KILL_COUNT=0
for pid in $STALE_PIDS; do
    if ! echo "$INTERACTIVE_PIDS" | grep -q "^${pid}$"; then
        KILL_PIDS="$KILL_PIDS $pid"
        KILL_COUNT=$((KILL_COUNT + 1))
    fi
done

# Calculate memory
MEM_MB=$(ps aux | grep "[c]laude.*stream-json" | awk '{sum += $6} END {printf "%.0f", sum/1024}')

echo "Found $KILL_COUNT stale Claude subagent processes (~${MEM_MB} MB RAM)"
echo "Preserving $(echo "$INTERACTIVE_PIDS" | grep -c . 2>/dev/null || echo 0) interactive session(s)"

if [ "$MODE" = "--kill" ]; then
    if [ -z "$KILL_PIDS" ]; then
        echo "Nothing to kill."
        exit 0
    fi
    echo "Killing $KILL_COUNT processes..."
    echo "$KILL_PIDS" | xargs kill 2>/dev/null || true
    sleep 1
    # Force kill any survivors
    SURVIVORS=$(echo "$KILL_PIDS" | xargs ps -p 2>/dev/null | tail -n +2 | awk '{print $1}')
    if [ -n "$SURVIVORS" ]; then
        echo "Force killing $(echo "$SURVIVORS" | wc -w | tr -d ' ') survivors..."
        echo "$SURVIVORS" | xargs kill -9 2>/dev/null || true
    fi
    echo "Done. Freed ~${MEM_MB} MB RAM."
else
    echo ""
    echo "Dry run — no processes killed."
    echo "Run with --kill to actually kill them:"
    echo "  ./scripts/kill-stale-claude.sh --kill"
fi

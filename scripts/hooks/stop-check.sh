#!/bin/bash
# Claude Code Stop hook for host sessions: refuse to finish while `make check` is red (tools/harness/stop_check.py).
# Inside the agent container the image's root-owned copy runs from managed settings instead; stop_check.py
# exits at once when started from this checkout there, so the check never runs twice.
exec python3 -I "$(cd "$(dirname "$0")/../.." && pwd)/tools/harness/stop_check.py"

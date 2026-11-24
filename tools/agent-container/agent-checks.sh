#!/bin/bash
# Critical isolation checks, run as the agent user before every session (agent-session) and by
# `bin/agent verify`. Every check tests the boundary itself (capabilities, mounts, network, file ownership,
# token scope), never a marker variable. Any FAIL exits 1, and agent-session then refuses to start Claude.
# Read-only: nothing here changes state or prints a secret.
set -u
REPO_SLUG=${AGENT_REPO_SLUG:-Ugur22/ai-subtitles}
fails=0
pass() { echo "PASS $1"; }
fail() { echo "FAIL $1"; fails=$((fails + 1)); }
check() { local name=$1; shift; if "$@" >/dev/null 2>&1; then pass "$name"; else fail "$name"; fi; }
refute() { local name=$1; shift; if "$@" >/dev/null 2>&1; then fail "$name"; else pass "$name"; fi; }
http_code() { curl -q -s -o /dev/null -w '%{http_code}' --max-time "${2:-6}" "$1" 2>/dev/null; }
reachable() { case $(http_code "$1") in 000) return 1 ;; *) return 0 ;; esac; }
tcp_open() { timeout 5 bash -c "exec 3<>/dev/tcp/$1/$2" 2>/dev/null; }
not_writable() { [ -e "$1" ] && [ "$(stat -c %u "$1")" = 0 ] && ! ( : >> "$1" ) 2>/dev/null; }
cap() { awk -v k="$1:" '$1 == k {print $2}' /proc/self/status; }

# --- privileges ---
refute "user:not-root" test "$(id -u)" = 0
check  "caps:effective-none" test "$(cap CapEff)" = 0000000000000000
check  "caps:permitted-none" test "$(cap CapPrm)" = 0000000000000000
check  "caps:bounding-none" test "$(cap CapBnd)" = 0000000000000000
check  "no-new-privileges" test "$(awk '$1 == "NoNewPrivs:" {print $2}' /proc/self/status)" = 1
refute "sudo:unavailable" sudo -n true
refute "iptables:not-changeable" iptables -A OUTPUT -j ACCEPT

# --- host exposure ---
for s in /var/run/docker.sock /run/docker.sock /run/host-services/docker.proxy.sock; do refute "docker-socket:absent:$s" test -e "$s"; done
refute "docker-host:unset" test -n "${DOCKER_HOST:-}"
refute "ssh-agent:absent" test -n "${SSH_AUTH_SOCK:-}"
refute "host-services:absent" test -e /run/host-services
# Docker Desktop bind mounts of macOS paths show up with these filesystem types; named volumes don't.
host_fs=$(awk '{for (i = 1; i <= NF; i++) if ($i == "-") {print $(i + 1), $5; break}}' /proc/self/mountinfo \
  | grep -E '^(virtiofs|fakeowner|grpcfuse|fuse\.grpcfuse|osxfs|fuse\.osxfs|9p) ' || true)
check  "mounts:no-host-bind" test -z "$host_fs"
# The account's real home, not $HOME: callers such as agent-verify run with a throwaway HOME.
real_home=$(getent passwd "$(id -un)" | cut -d: -f6)
for d in "$real_home/.ssh" "$real_home/.aws" "$real_home/.config/gcloud" "$real_home/.config/gh" /Users/ugurertas/.config /Users/ugurertas/.ssh; do
  refute "home:absent:$d" test -e "$d"
done
refute "secrets:no-prod-env" test -e /work/ai-subtitles/backend/.env
secret_env=$(env | cut -d= -f1 | grep -E 'SERVICE_KEY|STRIPE|SUPABASE|AWS_|GOOGLE_APPLICATION|GCLOUD|CLOUDSDK|HUGGINGFACE|GROQ|XAI|DEEPSEEK|PRIVATE_KEY' || true)
check  "secrets:no-prod-env-vars" test -z "$secret_env"

# --- network: default deny, allowlist works ---
refute "net:blocked:example.com" reachable https://example.com
refute "net:blocked:1.1.1.1" reachable https://1.1.1.1
refute "net:blocked:host.docker.internal" reachable http://host.docker.internal
refute "net:blocked:ssh-github" tcp_open github.com 22
check  "net:allowed:api.github.com" test "$(http_code https://api.github.com/zen)" = 200
check  "net:allowed:api.anthropic.com" reachable https://api.anthropic.com
check  "net:allowed:pypi.org" test "$(http_code https://pypi.org/simple/pip/)" = 200
check  "net:ipv6-disabled" test "$(cat /proc/sys/net/ipv6/conf/all/disable_ipv6 2>/dev/null)" = 1

# --- trusted enforcement is immutable to the agent ---
for f in /etc/claude-code/managed-settings.json /etc/claude-code/managed-settings.sha256 /etc/gitconfig \
         /etc/agent-image-commit /usr/local/bin/agent-session /usr/local/bin/agent-checks.sh /usr/local/bin/agent-verify \
         /usr/local/bin/init-firewall.sh /usr/local/bin/git-credential-agent /usr/local/bin/gh \
         /usr/local/lib/ai-subs-harness/stop_check.py /usr/local/lib/ai-subs-harness/ledger.py \
         /usr/local/lib/ai-subs-harness/ledger_report.py "$(command -v claude)"; do
  check "immutable:$f" not_writable "$(readlink -f "$f")"
done
refute "immutable:/etc/claude-code-dir" mkdir /etc/claude-code/managed-settings.d
refute "immutable:/usr/local/lib/node_modules" touch /usr/local/lib/node_modules/.agent-probe
refute "immutable:/usr/local/lib/ai-subs-harness" touch /usr/local/lib/ai-subs-harness/.agent-probe
# The Stop hook and ledger run from managed settings (not removable by project or user settings) and can run.
check  "managed-hooks:stop-registered" grep -q 'python3 -I /usr/local/lib/ai-subs-harness/stop_check.py' /etc/claude-code/managed-settings.json
check  "managed-hooks:harness-readable" test -r /usr/local/lib/ai-subs-harness/stop_check.py -a -r /usr/local/lib/ai-subs-harness/ledger.py
# Readable by the agent (Claude Code silently drops managed settings it can't read) and unchanged.
ms_hash=$(sha256sum /etc/claude-code/managed-settings.json 2>/dev/null | cut -d' ' -f1)
check  "managed-settings:readable-and-hash" test -n "$ms_hash" -a "$ms_hash" = "$(cat /etc/claude-code/managed-settings.sha256 2>/dev/null)"
if [ "${AGENT_ALLOW_UNREVIEWED_IMAGE:-}" = 1 ]; then
  echo "WARN image:revision $(cat /etc/agent-image-commit) (unreviewed build explicitly allowed)"
else
  check "image:reviewed-revision" grep -Eq '^[0-9a-f]{40}$' /etc/agent-image-commit
fi

# --- GitHub credential: present, rotated by the host, scoped to this repository only ---
check  "token:present" test -s /run/agent-token/token
refute "token:not-writable" sh -c ': >> /run/agent-token/token'
repos=$(curl -q -s --max-time 10 -H @<(printf 'Authorization: Bearer %s\n' "$(cat /run/agent-token/token 2>/dev/null)") \
  https://api.github.com/installation/repositories | jq -r '[.total_count, (.repositories // [] | map(.full_name) | join(","))] | @tsv' 2>/dev/null)
check  "token:single-repo:$REPO_SLUG" test "$repos" = "$(printf '1\t%s' "$REPO_SLUG")"

echo "agent-checks: fails=$fails image=$(cat /etc/agent-image-commit 2>/dev/null)"
[ "$fails" -eq 0 ]

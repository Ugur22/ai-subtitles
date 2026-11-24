#!/bin/bash
# Egress allowlist for the agent container. Run by `bin/agent up` in a separate, short-lived container that
# shares the agent's network namespace and alone holds NET_ADMIN; the agent container never does, so the
# agent can't change these rules. Default DROP; only DNS, loopback, established flows and the allowlisted
# destinations below pass. Same ipset approach as Anthropic's reference container, minus outbound SSH and
# minus the host network (so host.docker.internal and services on your Mac stay unreachable).
set -euo pipefail
IFS=$'\n\t'

REQUIRED_DOMAINS=(api.anthropic.com pypi.org files.pythonhosted.org download.pytorch.org registry.npmjs.org)
OPTIONAL_DOMAINS=(claude.ai console.anthropic.com download-r2.pytorch.org)

docker_dns=$(iptables-save -t nat | grep "127\.0\.0\.11" || true)

iptables -F; iptables -X
iptables -t nat -F; iptables -t nat -X
iptables -t mangle -F; iptables -t mangle -X
ipset destroy agent-allow 2>/dev/null || true

# Docker's embedded resolver lives on 127.0.0.11 through NAT rules; keep only those.
if [ -n "$docker_dns" ]; then
  iptables -t nat -N DOCKER_OUTPUT 2>/dev/null || true
  iptables -t nat -N DOCKER_POSTROUTING 2>/dev/null || true
  echo "$docker_dns" | xargs -L 1 iptables -t nat
fi

ipset create agent-allow hash:net

add_ip() {
  [[ "$1" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}(/[0-9]{1,2})?$ ]] || { echo "invalid address for $2: $1" >&2; exit 1; }
  ipset add agent-allow "$1" -exist
}

meta=$(curl -fsS --max-time 15 https://api.github.com/meta)
echo "$meta" | jq -e '.web and .api and .git' >/dev/null || { echo "GitHub meta response is incomplete" >&2; exit 1; }
while read -r cidr; do add_ip "$cidr" github; done < <(echo "$meta" | jq -r '(.web + .api + .git)[] | select(contains(":") | not)' | aggregate -q)

resolve() { dig +short +time=3 +tries=2 A "$1" | grep -E '^[0-9.]+$' || true; }
for d in "${REQUIRED_DOMAINS[@]}"; do
  ips=$(resolve "$d"); [ -n "$ips" ] || { echo "cannot resolve required domain $d" >&2; exit 1; }
  while read -r ip; do add_ip "$ip" "$d"; done <<< "$ips"
done
for d in "${OPTIONAL_DOMAINS[@]}"; do
  while read -r ip; do [ -n "$ip" ] && add_ip "$ip" "$d"; done <<< "$(resolve "$d")"
done

iptables -A INPUT -i lo -j ACCEPT
iptables -A OUTPUT -o lo -j ACCEPT
iptables -A OUTPUT -p udp --dport 53 -d 127.0.0.11 -j ACCEPT
iptables -A OUTPUT -p tcp --dport 53 -d 127.0.0.11 -j ACCEPT
iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -p tcp --dport 443 -m set --match-set agent-allow dst -j ACCEPT
iptables -A OUTPUT -j REJECT --reject-with icmp-admin-prohibited
iptables -P INPUT DROP
iptables -P FORWARD DROP
iptables -P OUTPUT DROP

curl -fsS --max-time 5 https://example.com >/dev/null 2>&1 && { echo "firewall check failed: example.com reachable" >&2; exit 1; }
curl -fsS --max-time 5 https://api.github.com/zen >/dev/null || { echo "firewall check failed: api.github.com unreachable" >&2; exit 1; }
echo "firewall: $(ipset list agent-allow | grep -c '^[0-9]') allowlisted networks, default deny"

#!/usr/bin/env bash
# Держит A-запись DuckDNS в актуальном состоянии (IP машины может смениться).
set -euo pipefail
set -a; . /root/crossparts/deploy/duckdns.env; set +a
RESP=$(curl -fsS --max-time 30 \
  "https://www.duckdns.org/update?domains=${DUCKDNS_DOMAIN}&token=${DUCKDNS_TOKEN}&ip=")
echo "$(date -Is) duckdns: ${RESP}"

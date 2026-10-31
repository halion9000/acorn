#!/usr/bin/env bash
# Limits the size of TCP segments for connections to and from the Timus network (192.168.249.0/24) through the site-to-site tunnel.
# People reach A.C.O.R.N through two tunnels (the Timus agent's WireGuard, then IPsec to Azure); together they leave less room per packet than the usual 1500 bytes
# (measured 2026-10-31: a 1300-byte ping passes, 1350 does not). Without this, small pages load and larger responses stall.
# Safe to run any number of times: each rule is added only if it is missing. Run by acorn-mss-clamp.service at boot.
set -eu
MSS=${ACORN_MSS:-1280}
NET=${ACORN_TIMUS_NET:-192.168.249.0/24}
for dir in -s -d; do
  iptables -t mangle -C FORWARD "$dir" "$NET" -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss "$MSS" 2>/dev/null ||
    iptables -t mangle -A FORWARD "$dir" "$NET" -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss "$MSS"
done

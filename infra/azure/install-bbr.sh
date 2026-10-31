#!/usr/bin/env bash
# One-time setup on the A.C.O.R.N VM: send TCP data in a smoothed stream (BBR congestion control with the fq packet scheduler) instead of back-to-back bursts.
#   sudo bash /srv/acorn/AiSOC/infra/azure/install-bbr.sh
# Why: measured 2026-10-31, the site-to-site tunnel to the Timus network loses packets that arrive in bursts. With the default (cubic) a 2 MB download stalled after
# about 13 KB and took 40-80 s; with BBR the same download finished in 20-35 s and pages load. Containers pick the setting up when they are (re)created, so run it
# BEFORE an update/restart (the update script recreates the containers). Applies to the whole VM, survives reboots, and is safe for other traffic.
set -eu
modprobe tcp_bbr
echo tcp_bbr > /etc/modules-load.d/acorn-bbr.conf
cat > /etc/sysctl.d/99-acorn-bbr.conf <<'CONF'
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
CONF
sysctl --system >/dev/null
for i in $(ls /sys/class/net | grep -E '^(eth|enP)'); do tc qdisc replace dev "$i" root fq; done
echo "congestion control: $(sysctl -n net.ipv4.tcp_congestion_control), qdisc: $(sysctl -n net.core.default_qdisc)"

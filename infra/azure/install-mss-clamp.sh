#!/usr/bin/env bash
# One-time setup on the A.C.O.R.N VM: runs acorn-mss-clamp.sh at every boot (the rules do not survive a restart on their own).
#   sudo bash /srv/acorn/AiSOC/infra/azure/install-mss-clamp.sh
set -eu
install -m 0755 /srv/acorn/AiSOC/infra/azure/acorn-mss-clamp.sh /usr/local/sbin/acorn-mss-clamp
# Remove the first, temporary 1200 rules if they are there, so only the measured value remains.
for dir in -s -d; do
  iptables -t mangle -D FORWARD "$dir" 192.168.249.0/24 -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1200 2>/dev/null || true
done
cat > /etc/systemd/system/acorn-mss-clamp.service <<'UNIT'
[Unit]
Description=Limit TCP segment size for the Timus tunnel
After=network-online.target
Wants=network-online.target
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/acorn-mss-clamp
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now acorn-mss-clamp.service
systemctl is-active acorn-mss-clamp.service
iptables -t mangle -S FORWARD | grep -i mss

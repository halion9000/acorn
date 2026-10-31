#!/usr/bin/env bash
# One-time setup on the A.C.O.R.N VM: the folder the Update button writes to, and the systemd units that run acorn-update-runner.sh when a request appears.
#   sudo bash /srv/acorn/AiSOC/infra/azure/install-update-watcher.sh
set -eu
install -d -m 0777 /srv/acorn/update-ctl
install -m 0755 /srv/acorn/AiSOC/infra/azure/acorn-update-runner.sh /usr/local/sbin/acorn-update-runner
cat > /etc/systemd/system/acorn-update.service <<'UNIT'
[Unit]
Description=Run the A.C.O.R.N update requested from its screen
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/acorn-update-runner
TimeoutStartSec=3600
UNIT
cat > /etc/systemd/system/acorn-update.path <<'UNIT'
[Unit]
Description=Watch for an A.C.O.R.N update request
[Path]
PathExists=/srv/acorn/update-ctl/request.json
Unit=acorn-update.service
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now acorn-update.path
systemctl is-active acorn-update.path

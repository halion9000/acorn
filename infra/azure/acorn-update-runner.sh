#!/usr/bin/env bash
# Runs on the A.C.O.R.N VM (started by acorn-update.path) when the Update button in A.C.O.R.N writes /srv/acorn/update-ctl/request.json.
# The request is never read for instructions: its arrival means "run the update script once". Output goes to last-run.log for the screen to show.
set -u
CTL=${ACORN_UPDATE_CTL:-/srv/acorn/update-ctl}
[ -f "$CTL/request.json" ] || exit 0
[ -e "$CTL/running" ] && exit 0
touch "$CTL/running"
mv "$CTL/request.json" "$CTL/request.taken.json"
: > "$CTL/last-run.log"
bash "${ACORN_UPDATE_SCRIPT:-/srv/acorn/AiSOC/infra/azure/update-acorn.sh}" >> "$CTL/last-run.log" 2>&1
rc=$?
echo "[$(date -u +%H:%M:%S)] update script exited with code $rc" >> "$CTL/last-run.log"
rm -f "$CTL/running"

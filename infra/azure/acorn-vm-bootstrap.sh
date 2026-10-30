#!/usr/bin/env bash
# First-boot setup for the A.C.O.R.N Linux VM (Ubuntu). Run once as root over the RMM session / Run Command:
#   sudo bash acorn-vm-bootstrap.sh
# It formats and mounts the 128 GB data disk (LUN 0) at /srv/acorn, installs Docker and moves Docker's storage onto that disk.
# Safe to run twice: it never formats a disk that already holds a filesystem.
set -euo pipefail

# SCSI sizes name the disk under scsi1; the newer NVMe sizes (the v6 series) name it under data/by-lun.
DISK=/dev/disk/azure/scsi1/lun0
[ -e "$DISK" ] || DISK=/dev/disk/azure/data/by-lun/0
MOUNT=/srv/acorn

[ -e "$DISK" ] || { echo "Data disk not found (is it attached at LUN 0?)" >&2; exit 1; }

if ! blkid "$DISK" >/dev/null 2>&1; then
  mkfs.ext4 -L acorn-data "$DISK"
fi
mkdir -p "$MOUNT"
UUID=$(blkid -s UUID -o value "$DISK")
grep -q "$UUID" /etc/fstab || echo "UUID=$UUID $MOUNT ext4 defaults,nofail 0 2" >> /etc/fstab
mountpoint -q "$MOUNT" || mount "$MOUNT"

if ! command -v docker >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y ca-certificates curl gnupg git jq postgresql-client-16
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

mkdir -p "$MOUNT/docker"
cat > /etc/docker/daemon.json <<JSON
{ "data-root": "$MOUNT/docker", "log-driver": "json-file", "log-opts": { "max-size": "50m", "max-file": "3" } }
JSON
systemctl restart docker
systemctl enable docker

# OpenSearch needs this kernel setting.
echo 'vm.max_map_count=262144' > /etc/sysctl.d/99-opensearch.conf
sysctl --system >/dev/null

echo "Ready: Docker data on $MOUNT. Next: get the code into $MOUNT/AiSOC and follow docs/AZURE_RUNBOOK.md."

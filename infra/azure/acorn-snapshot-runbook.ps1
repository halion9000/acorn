# Weekly snapshot of the A.C.O.R.N VM's OS disk (improvement A33). Keeps the newest four.
#
# Runs in the Azure Automation account `acorn-snapshots` (resource group rg-liveoak-ops) as that account's OWN managed identity, which is deliberately not the VM's identity:
# a compromised VM must not be able to delete its own backups. The identity needs the built-in role "Disk Snapshot Contributor" on the resource group, and nothing else.
# Incremental snapshots are billed only for the data that changed since the previous one.
$ErrorActionPreference = 'Stop'
Connect-AzAccount -Identity | Out-Null
$rg = 'rg-liveoak-ops'
$diskName = 'liveoak-acorn-vm_OsDisk_1_4d99608d48144d1284c65b0bd3594d0b'
$keep = 4
$disk = Get-AzDisk -ResourceGroupName $rg -DiskName $diskName
$cfg = New-AzSnapshotConfig -SourceUri $disk.Id -Location $disk.Location -CreateOption Copy -Incremental -Tag @{ purpose = 'acorn-weekly' }
$name = 'acorn-os-' + (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmm')
New-AzSnapshot -ResourceGroupName $rg -SnapshotName $name -Snapshot $cfg | Out-Null
Write-Output "Created snapshot $name"
$mine = Get-AzSnapshot -ResourceGroupName $rg | Where-Object { $_.Tags['purpose'] -eq 'acorn-weekly' } | Sort-Object TimeCreated -Descending
$old = $mine | Select-Object -Skip $keep
foreach ($s in $old) { Remove-AzSnapshot -ResourceGroupName $rg -SnapshotName $s.Name -Force | Out-Null; Write-Output "Removed $($s.Name)" }
Write-Output "Kept $([Math]::Min($mine.Count, $keep)) snapshot(s)."

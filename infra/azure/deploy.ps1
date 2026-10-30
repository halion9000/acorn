<#
  Deploys infra/azure/main.bicep. Safe by default: with no switch it only PREVIEWS (what-if) and creates nothing.

    .\deploy.ps1            # preview
    .\deploy.ps1 -Deploy    # create everything (costs money: see README)

  The two admin passwords are generated here, handed straight to the deployment and stored in Key Vault. They are never printed or written to a file.
  Run it in a PowerShell where `az login` has been done and the MCPP subscription is the default.
#>
param(
    [switch]$Deploy,
    [string]$ResourceGroup = 'rg-liveoak-ops',
    [string]$Parameters = "$PSScriptRoot\main.parameters.json"
)
$ErrorActionPreference = 'Stop'

if (-not (Test-Path $Parameters)) { throw "Missing $Parameters (copy main.parameters.example.json and fill in your SSH public key)." }

function New-Secret([int]$Length = 32) {
    # Upper, lower, digit and symbol are all present (Windows and Azure Postgres both require complexity); no characters that need quoting.
    $sets = @('ABCDEFGHJKLMNPQRSTUVWXYZ', 'abcdefghijkmnopqrstuvwxyz', '23456789', '#%+=_-')
    $rng = [System.Security.Cryptography.RandomNumberGenerator]
    $chars = foreach ($s in $sets) { $s[$rng::GetInt32($s.Length)] }
    $all = ($sets -join '')
    $chars += 1..($Length - $chars.Count) | ForEach-Object { $all[$rng::GetInt32($all.Length)] }
    -join ($chars | Sort-Object { $rng::GetInt32(1000000) })
}

$subscription = az account show --query "{name:name, id:id}" -o tsv
Write-Host "Subscription: $subscription"
az group show --name $ResourceGroup --query name -o tsv | Out-Null

$core = New-Secret
$pg = New-Secret
$template = "$PSScriptRoot\main.bicep"

if (-not $Deploy) {
    Write-Host 'Preview only (add -Deploy to create the resources).'
    az deployment group what-if --resource-group $ResourceGroup --template-file $template --parameters "@$Parameters" `
        coreAdminPassword=$core postgresAdminPassword=$pg --no-pretty-print --result-format ResourceIdOnly
    return
}

Write-Host 'Creating the resources (this takes 15 to 30 minutes)...'
$out = az deployment group create --resource-group $ResourceGroup --template-file $template --parameters "@$Parameters" `
    coreAdminPassword=$core postgresAdminPassword=$pg --query properties.outputs -o json | ConvertFrom-Json
$vault = $out.keyVaultName.value

# The vault uses role-based access: Owner on the subscription does not let you write secrets, so grant yourself that on this vault only.
$me = az ad signed-in-user show --query id -o tsv
$vaultId = az keyvault show --name $vault --query id -o tsv
az role assignment create --assignee-object-id $me --assignee-principal-type User --role 'Key Vault Secrets Officer' --scope $vaultId | Out-Null
Start-Sleep -Seconds 60   # role assignments take a moment to apply

az keyvault secret set --vault-name $vault --name core-vm-admin-password --value $core | Out-Null
az keyvault secret set --vault-name $vault --name postgres-admin-password --value $pg | Out-Null
# The limited database account the application connects as (so row-level security is enforced); the runbook creates the role with this password.
az keyvault secret set --vault-name $vault --name aisoc-app-db-password --value (New-Secret 40) | Out-Null

Write-Host "Done. Key Vault: $vault"
Write-Host "A.C.O.R.N VM private IP: $($out.acornPrivateIp.value)"
Write-Host "CORE VM private IP:      $($out.corePrivateIp.value)"
Write-Host "Postgres host:           $($out.postgresHost.value)"
Write-Host 'Passwords are in Key Vault (core-vm-admin-password, postgres-admin-password, aisoc-app-db-password). Next: docs/AZURE_RUNBOOK.md.'

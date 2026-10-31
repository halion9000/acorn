<#
  Lets the CORE VM's identity run the A.C.O.R.N update on the A.C.O.R.N VM, and nothing else.

  Creates the custom role in role-acorn-deployer.json (read the VM; read, write and delete its Run Command resources) and assigns it to the CORE VM's own identity, scoped to the A.C.O.R.N VM only.
  Run it once, in a PowerShell where `az login` was done as an Owner of the subscription. Safe to run twice. To undo: `az role assignment delete` for the same assignee, role and scope.
#>
$ErrorActionPreference = 'Stop'
$rg = 'rg-liveoak-ops'
$roleName = 'LiveOak A.C.O.R.N Deployer'

$existing = az role definition list --name $roleName --query "[0].name" -o tsv
if (-not $existing) {
    az role definition create --role-definition "$PSScriptRoot\role-acorn-deployer.json" --query roleName -o tsv
    if ($LASTEXITCODE) { throw 'could not create the role' }
} else { "role already exists: $roleName" }

$core = az vm show -g $rg -n liveoak-core-vm --query identity.principalId -o tsv
$acorn = az vm show -g $rg -n liveoak-acorn-vm --query id -o tsv
az role assignment create --assignee-object-id $core --assignee-principal-type ServicePrincipal --role $roleName --scope $acorn --query "{role:roleDefinitionName,scope:scope}" -o json
if ($LASTEXITCODE) { throw 'could not assign the role' }
"Done. The CORE VM can now run Run Command on $acorn and nothing else."

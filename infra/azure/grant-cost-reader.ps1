<#
  Lets the A.C.O.R.N VM's identity READ this resource group's costs, for Settings > Azure spend. Read only: the built-in role "Cost Management Reader", scoped to the one resource group.
  Run it once, in a PowerShell where `az login` was done as an Owner of the subscription. Safe to run twice. To undo: `az role assignment delete` for the same assignee, role and scope.
#>
$ErrorActionPreference = 'Stop'
$rg = 'rg-liveoak-ops'
$principal = az vm show -g $rg -n liveoak-acorn-vm --query identity.principalId -o tsv
if (-not $principal) { throw 'the A.C.O.R.N VM has no managed identity' }
$scope = az group show -n $rg --query id -o tsv
az role assignment create --assignee-object-id $principal --assignee-principal-type ServicePrincipal --role 'Cost Management Reader' --scope $scope --query "{role:roleDefinitionName,scope:scope}" -o json
if ($LASTEXITCODE) { throw 'could not assign the role' }
"Done. The A.C.O.R.N VM can now read costs for $rg and nothing else."

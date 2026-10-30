# Azure infrastructure (Live Oak operations)

`main.bicep` describes everything in `docs/AZURE_MIGRATION_PLAN.md` that Azure holds: a private network with no inbound access from the internet, a Linux VM for A.C.O.R.N, a Windows VM for CORE, a managed
Postgres (private only), a Key Vault, backups, a log workspace with a daily cap, and a monthly budget with alerts.

## What was checked on the subscription (2026-10-30, read-only)

- Subscription: **MCPP Subscription** (`34497679-4e8a-41d5-a9ae-a3e03c24981f`), billed to the **RAMP** billing profile, which carries the $5,000 Azure credit (valid for a year). Hal is Owner.
- **Region: Central US.** East US 2 and South Central US refuse the sizes we want (`NotAvailableForSubscription`); East US refuses the B-series. Central US allows `Standard_D4s_v6`, `Standard_D2s_v6`,
  `Standard_B2ms` and `Standard_B4ms` (the v5 sizes are listed but the quota is 0).
- The resource providers Compute, Network, DBforPostgreSQL, KeyVault, RecoveryServices, Storage and OperationalInsights are **not registered** yet (registering is free and is the first step).
- One resource group exists (`mcpp-purchase`, East US); it is left alone.

## Order of work

Every step that creates something waits for a go from Hal.

1. Register the resource providers (free).
2. Create the resource group `rg-liveoak-ops` in `centralus`.
3. Preview: `az deployment group what-if` with the parameters below. Nothing is created by a preview.
4. Deploy: `az deployment group create`. The two passwords are generated at that moment, passed straight in, and stored in Key Vault. They are never written to a file or printed.
5. Check: both VMs reach each other and the internet outbound; nothing answers from outside; backups show a first recovery point after the first night.

```bash
az provider register --namespace Microsoft.Compute --namespace Microsoft.Network      # one at a time; also DBforPostgreSQL, KeyVault, RecoveryServices, Storage, OperationalInsights
az group create --name rg-liveoak-ops --location centralus --tags project=liveoak-ops
az deployment group what-if --resource-group rg-liveoak-ops --template-file main.bicep --parameters @main.parameters.json
```

`main.parameters.json` holds only non-secret values (the SSH public key, the budget email and start date). See `main.parameters.example.json`.

## Known limits

- The template compiles and a `what-if` against the subscription succeeded (25 resources to create, 2026-10-30). Nothing has been deployed. The subscription has 0 quota for the DSv5 family in Central US, so the A.C.O.R.N VM is `Standard_D4s_v6`.
- Postgres extensions A.C.O.R.N's migrations need (`pg_trgm`, `pgcrypto`, `uuid-ossp`, `btree_gin`, `citext`) are allow-listed, but the migrations have not been run against a managed server yet (Phase 2).
- Nothing inside the VMs is configured here (Docker, CORE, the RMM agent, Tailscale). That is Phase 2 and 3 of the plan.

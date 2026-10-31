# Azure runbook: from an empty resource group to a running A.C.O.R.N and CORE

Written 2026-10-30, **before anything was deployed**. Every step below is a plan, not something that has been run: the first real run will find small corrections, and this file should be corrected as they are found. Companion to `docs/AZURE_MIGRATION_PLAN.md` (why) and `infra/azure/` (the template and scripts).

## Decisions taken (Hal, 2026-10-30)

- **AI path:** try the normal Claude plan first. CORE's shim runs Claude Code on the CORE Windows VM, so Claude Code is signed in once on that VM (a browser sign-in in the VM's desktop session). If the plan's terms or limits do not allow an unattended service, move to an Anthropic API key. Not yet checked against Anthropic's terms: do that before relying on it.
- **Access, now:** the NinjaOne remote session (RMM agent on both VMs). **Access, later:** NordLayer or Tailscale to reach the private network. **Long term:** a public HTTPS address for the client portal only, behind a web application firewall; the admin console stays private.
- **Region:** Central US (the sizes we need are only allowed there). **Credit:** $5,000, valid a year.

## 0. Before deploying

1. `az login`, default subscription MCPP (`34497679-4e8a-41d5-a9ae-a3e03c24981f`). `infra/azure/main.parameters.json` exists locally (not committed).
2. `infra/azure/deploy.ps1` with no switch is a preview and creates nothing. It was run on 2026-10-30 and succeeded.

## 1. Create the infrastructure

`infra/azure/deploy.ps1 -Deploy` (15 to 30 minutes). It generates the two admin passwords and a third for the application's limited database account, stores all three in Key Vault and prints no secret. It ends by printing the private IP of each VM and the Postgres host. **Costs about $300 to $430 a month from the credit.**

Check afterwards: both VMs show Running; the Recovery Services vault lists both VMs; the budget alert exists; no public inbound rule exists on the network security group.

### Deployed 2026-10-30 (checked afterwards)

Resource group `rg-liveoak-ops` (Central US): `liveoak-acorn-vm` (Linux, D4s_v6, 10.20.1.4), `liveoak-core-vm` (Windows, B2ms, 10.20.2.4), Postgres `liveoak-pg-dnzpna3fw56s4` (private only, Standard_B2s, no high availability), Key Vault `liveoak-kv-dnzpna3fw56s4`, Recovery Services vault `liveoak-rsv` (both VMs on the daily 14-day policy; the first backup was still pending), budget `liveoak-monthly` ($450). Verified: no public IP addresses, no inbound allow rules on any of the three network security groups, Postgres public access disabled.

**What went wrong, and the rule that comes from it.** The Key Vault firewall denies everything except the private network, so the first run could not store the three passwords, and the script printed "Done" anyway. The passwords were reset and stored (this machine allowed in for the length of the writes, then removed); `deploy.ps1` now does that itself and stops on any failure. To read a secret from a laptop, allow its address briefly (`az keyvault network-rule add` ... then `remove`), or read it from a VM, which can reach the vault privately through its own identity.

### Linux VM prepared (2026-10-30, through Azure Run Command; nothing was installed by hand)

`acorn-vm-bootstrap.sh` ran on `liveoak-acorn-vm`: the 128 GB data disk is mounted at `/srv/acorn`, Docker 29 runs with its storage there (`docker run hello-world` works), `vm.max_map_count` is 262144. Two corrections came out of checking it:

- **The disk path.** The v6 sizes present the data disk as NVMe (`/dev/disk/azure/data/by-lun/0`), not `scsi1`; the script handles both now.
- **The Postgres address.** The server's address is `liveoak-pg-dnzpna3fw56s4.postgres.database.azure.com` (it resolves to 10.20.3.4 from inside the network and port 5432 answers there). The `...liveoak.private...` name the template first printed does not resolve; the template output now gives the right one.
- **Key Vault from the VMs.** The vault firewall blocked the VMs too, because they reach it over the public path. Both VM subnets now carry a Key Vault service endpoint and the vault allows exactly those two subnets (done with the CLI and written into `main.bicep`). Checked from the Linux VM: its identity reads `postgres-admin-password` and `aisoc-app-db-password` (HTTP 200). The Windows VM has not been checked yet. **Do not re-run `deploy.ps1 -Deploy` on this resource group as it is:** it would generate new admin passwords and overwrite the stored ones.

### Database restored and the stack running (2026-10-30)

The local database was dumped (read-only) and restored into the managed server through a temporary private storage account (deleted afterwards): 155 tables, row counts equal to the local ones at that moment, `aisoc_app` is not a superuser. `AISOC_CREDENTIAL_KEY` was copied unchanged from the running local API into Key Vault (`aisoc-credential-key`). `/srv/acorn/AiSOC/.env` on the VM (mode 600) holds freshly generated service tokens and the two database URLs, built from Key Vault; none of it is committed. The images were built on the VM and `docker compose -f docker-compose.yml -f infra/azure/docker-compose.azure.yml up -d --build` brought up all 20 containers healthy. The API logs `db.rls_enforced role=aisoc_app` (the superuser warning is gone), `/health` answers 200 and the web container answers.

Not copied, on purpose: ClickHouse, OpenSearch, Neo4j and Qdrant start empty (rebuilt from Postgres and the feeds). The AI features need the Claude shim on the CORE VM and are not working in Azure yet. The VM's code is the archive of commit e960d5af; update it by archiving a newer commit and rebuilding. The API and web are published on the VM's private address only (`ACORN_BIND_IP=10.20.1.4` in `.env`; `http://10.20.1.4:8000` and `:3000`), never on the internet: from the CORE VM, `http://10.20.1.4:8000/health` answers 200, and the CORE VM's identity reads Key Vault (HTTP 200). **This Azure copy runs alongside the local one:** both poll the same vendors, so expect the same alerts to arrive in each.

## 2. Reach the machines

Install the NinjaOne agent on both VMs through each VM's Run Command (Azure portal > the VM > Run command), using the organisation's installer. From then on use the NinjaOne remote session. Add NordLayer or Tailscale later; neither is needed for the steps below.

## 3. A.C.O.R.N VM (Linux)

1. Run `infra/azure/acorn-vm-bootstrap.sh` as root (it mounts the data disk at `/srv/acorn`, installs Docker, moves Docker's storage there, sets the kernel setting OpenSearch needs). Safe to run twice.
2. Get the code into `/srv/acorn/AiSOC` (a clone of the `halion9000/acorn` repository; the repository is private, so use a read-only deploy key kept in Key Vault, never a personal token).
3. **Database.** From the old machine take a dump: `pg_dump -Fc -U aisoc aisoc > aisoc.dump`. Restore it into the managed server as the admin account (`postgres-admin-password` in Key Vault; the admin login is `liveoakadmin`; the host is the `postgresHost` output; `sslmode=require`) with `pg_restore --no-owner --no-privileges`. The extensions the migrations need are already allow-listed on the server (`pg_trgm`, `pgcrypto`, `uuid-ossp`, `btree_gin`, `citext`); create them in the database first (`CREATE EXTENSION ...`) as the admin.
4. **The limited application account**, so row-level security is enforced: with `AISOC_APP_DB_PASSWORD` set to the `aisoc-app-db-password` secret, run `psql -f scripts/provision_app_role.sql` against the managed server as the admin. Check: `SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'aisoc_app'` shows `f, f`.
5. **Pointing the stack at it.** `infra/azure/docker-compose.azure.yml` is an override that sends every service that uses the database to the managed server (as `aisoc_app`, with the owner account only for migrations through `MIGRATION_DATABASE_URL`) and stops the local `postgres` container from starting or being waited for. Put `AZURE_DATABASE_URL` and `AZURE_MIGRATION_DATABASE_URL` in `.env` (formats are in the file's header; the values come from Key Vault), then `docker compose -f docker-compose.yml -f infra/azure/docker-compose.azure.yml up -d`. It was checked by rendering the combined file (`docker compose config`: no service still depends on postgres and the URLs land on the right services); it has **not been started against a real managed server**. The services behind profiles (osquery-tls, honeytokens, purple-team) get the same override when their profile is enabled. Regenerate the file if the root compose file's database settings change.
6. Copy the settings that must not change: **`AISOC_CREDENTIAL_KEY` must be the same value as today** or every stored connector credential becomes unreadable. Take it, and the CORE feed token, from the current environment into Key Vault; do not generate new ones.
7. Start the stack. Check: the health page is green; the migrations report applied; the platform no longer shows the superuser warning.
8. Redis, Kafka, ClickHouse, OpenSearch, Neo4j and Qdrant stay on the VM's data disk. ClickHouse, OpenSearch, Neo4j and Qdrant can be rebuilt from Postgres and the feeds where needed; do not assume a copied volume works until it has been started and queried.

## 4. CORE VM (Windows)

1. Connect with the NinjaOne remote session (or RDP over the private network once a VPN exists). The administrator password is `core-vm-admin-password` in Key Vault.
2. Install CORE as on the current machine; copy its configuration folder and vendor keys from Key Vault, not by email or chat.
3. Install Claude Code and sign in once (this is the "normal plan" path). Run `hermes -p core chat -Q -q 'say ok'` as the check the project's `CLAUDE.md` asks for.
4. Point CORE at the A.C.O.R.N VM's private IP. Turn on automatic sign-in and add a scheduled check that CORE is running, because CORE needs a signed-in desktop session.
5. Check: sweeps report on the platform health page; sign-ins, devices and alerts arrive.

## 5. Cut over

Run both sides side by side for a few days and compare counts (alerts, devices, cases, inventory). Switch the team to the Azure copy, stop the local copy and keep its last backup for a month. Rehearse one restore from the Azure backup before stopping the local copy.

## What is not known yet

- Whether the normal Claude plan permits an unattended service (check the terms; fall back to an API key).
- Whether the stack starts cleanly against the managed Postgres (the override renders correctly but has not been run).
- The exact NinjaOne agent installer for the VMs.
- Whether the first real deployment needs corrections to the template (the preview does not catch everything, for example backup item names and quota at create time).

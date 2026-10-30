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

## 2. Reach the machines

Install the NinjaOne agent on both VMs through each VM's Run Command (Azure portal > the VM > Run command), using the organisation's installer. From then on use the NinjaOne remote session. Add NordLayer or Tailscale later; neither is needed for the steps below.

## 3. A.C.O.R.N VM (Linux)

1. Run `infra/azure/acorn-vm-bootstrap.sh` as root (it mounts the data disk at `/srv/acorn`, installs Docker, moves Docker's storage there, sets the kernel setting OpenSearch needs). Safe to run twice.
2. Get the code into `/srv/acorn/AiSOC` (a clone of the `halion9000/acorn` repository; the repository is private, so use a read-only deploy key kept in Key Vault, never a personal token).
3. **Database.** From the old machine take a dump: `pg_dump -Fc -U aisoc aisoc > aisoc.dump`. Restore it into the managed server as the admin account (`postgres-admin-password` in Key Vault; the admin login is `liveoakadmin`; the host is the `postgresHost` output; `sslmode=require`) with `pg_restore --no-owner --no-privileges`. The extensions the migrations need are already allow-listed on the server (`pg_trgm`, `pgcrypto`, `uuid-ossp`, `btree_gin`, `citext`); create them in the database first (`CREATE EXTENSION ...`) as the admin.
4. **The limited application account**, so row-level security is enforced: with `AISOC_APP_DB_PASSWORD` set to the `aisoc-app-db-password` secret, run `psql -f scripts/provision_app_role.sql` against the managed server as the admin. Check: `SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'aisoc_app'` shows `f, f`.
5. **Pointing the stack at it.** The root `docker-compose.yml` hard-codes `DATABASE_URL=postgresql+asyncpg://aisoc:${POSTGRES_PASSWORD}@postgres:5432/aisoc` on each service, so a compose override that sets `DATABASE_URL` to the managed server (as `aisoc_app`) for each of those services, and removes the local `postgres` service, is a piece of work that has **not been done yet**. Migrations must still run as the owner account; the running services use `aisoc_app`.
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
- The compose override for the managed Postgres (step 3.5).
- The exact NinjaOne agent installer for the VMs.
- Whether the first real deployment needs corrections to the template (the preview does not catch everything, for example backup item names and quota at create time).

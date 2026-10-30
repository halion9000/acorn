# Moving CORE and A.C.O.R.N to Azure: plan

Written 2026-10-30. **Prices are rough list prices from memory (US region, pay-as-you-go) and have not been checked in Azure's calculator: check them before committing.** Everything under "what is running today" was measured on the current machine.

## Goal

Neither system depends on one person's computer. All access is over a VPN or the RMM tool, with no admin surface on the public internet. A client portal comes later and is the only public piece.

## What is running today (measured)

- 21 containers use about **5 GB of RAM** in total and the CPU is almost idle. The Postgres database is **1 GB**; all data volumes together are about **20 GB**.
- A.C.O.R.N: API, web, agents, actions, connectors, enrichment, fusion, honeytokens, ingest, purple-team, realtime, threatintel, ueba, and the stores: Postgres, Redis, Kafka (with ZooKeeper and a UI), ClickHouse, OpenSearch, Neo4j, Qdrant, plus the LiteLLM AI gateway.
- CORE: a Windows desktop app (an Electron window, PowerShell, a Windows config folder) that holds every vendor key and runs the agents. Its agents also build and start A.C.O.R.N locally.
- The AI path today: A.C.O.R.N asks LiteLLM, which asks a small shim on CORE, which runs Claude on **your Claude Code plan**.

## Target

Two VMs in one private network, plus one managed database.

| Piece | What | Why |
|---|---|---|
| **acorn-vm** | Linux (Ubuntu), 4 vCPU and 16 GB, 128 GB data disk | The compose stack. About 5 GB used today, so there is room to grow. |
| **core-vm** | Windows, 2 vCPU and 8 GB (a burstable size is enough) | CORE needs Windows and a signed-in desktop session. |
| **Postgres** | Azure Database for PostgreSQL, Flexible Server | See the datastore answer below. |
| **Network** | One virtual network, no inbound from the internet | CORE sends its feed to A.C.O.R.N on a private address. |
| **Secrets** | Azure Key Vault | Holds `AISOC_CREDENTIAL_KEY`, the feed token and API keys. |
| **Backups** | Azure Backup for both VMs, Postgres point-in-time restore | Replaces the local backup script. |
| **Your two Windows 365 Cloud PCs** | Admin workstations only | They reach the servers over the private network. They are not used as servers. |

### Should there be a datastore now? Yes, for Postgres.

- **Move Postgres to the managed service from day one** (about $30 to $60 a month for a small burstable size). Moving it later means a second migration, and it is the one store whose loss would hurt.
- It also fixes a known weakness: the app currently connects as a database superuser, so row-level security (the thing that keeps one client's data from another) is **not enforced**. With a managed server there is an admin account and a separate limited application account, so the application connects without the bypass. This must be done before a client portal in any case.
- **Leave the other stores on the VM for now** (Redis, Kafka, ClickHouse, OpenSearch, Neo4j, Qdrant), on a separate data disk so they can be moved later. They are small, they have no good native Azure equivalent, and moving them gains little today.
- Revisit later: Redis to Azure Cache for Redis, Kafka to Event Hubs, if you ever want less to look after.

## Access and security

- **No public inbound ports.** Network rules allow only outbound traffic (the system must call vendor APIs).
- **Reaching the machines:** the RMM tool's remote session, or a private mesh such as Tailscale (free for this size). Azure's own VPN gateway and Bastion each cost about $140 a month, which is not worth it here.
- **CORE to A.C.O.R.N** stays on private addresses inside the network, so the feed token never crosses the internet.
- **Sign-in to A.C.O.R.N:** move to Entra ID single sign-on (it fits Azure and the later portal).
- **Later, the client portal:** the only public endpoint, behind HTTPS and a web application firewall, separate from the admin console, and showing each client only its own tenant's data.
- Install the RMM agent on both VMs for patching and monitoring.

## The AI model path (the cost I cannot size yet)

The Claude shim on your PC will not exist in Azure. Options: an Anthropic API key (pay per use), or a model service inside Azure. **Open question:** whether Anthropic's terms allow a Claude Code *subscription* to power an unattended service. API keys are the supported route for server work. Decide this before the move; it is the one cost not in the table.

## Cost (rough, per month)

| Item | About |
|---|---|
| acorn-vm (4 vCPU, 16 GB) + 128 GB disk | $160 to $200 |
| core-vm (2 vCPU, 8 GB Windows, burstable) | $70 to $130 |
| Managed Postgres (small, burstable, with storage) | $30 to $60 |
| Backups, Key Vault, logs, public IP | $20 to $40 |
| **Total** | **about $280 to $430** |
| AI model usage | not included, depends on use |

At this rate the $5,000 credit lasts the year with some left over. The credit does not expire for a year, so there is no reason to buy reservations.

## Phases

**Phase 0: decisions (before touching Azure).** Confirm the AI path; choose region; choose how you will reach the machines (RMM or Tailscale); check the credit's details in the billing page.

**Phase 1: build the base.** Resource group; virtual network with no inbound; the two VMs; managed Postgres with an admin and an application account; Key Vault; backups switched on. *Check:* both VMs reach each other and the internet outbound, and nothing answers from outside.

**Phase 2: A.C.O.R.N.** Install Docker on acorn-vm; take a Postgres dump and restore it into the managed server; restore or rebuild the other stores (ClickHouse, OpenSearch, Neo4j and Qdrant data can be rebuilt from Postgres and the feeds where needed); set the environment (with the credential key from Key Vault); start the stack. *Check:* migrations apply, the health page is green, row-level security is enforced for the application account (the superuser warning disappears).

**Phase 3: CORE.** Install CORE on core-vm; copy its settings and the vendor keys (through Key Vault, not by email); point it at acorn-vm's private address; keep the desktop session signed in (auto-logon). *Check:* sweeps report on the platform health page; sign-ins, devices and alerts arrive.

**Phase 4: cut over.** Run both sides in parallel for a few days; compare counts; switch the team to the Azure copy; stop the local copy but keep the last backup for a month.

**Phase 5: harden and extend.** Entra sign-in, a build-and-deploy pipeline (GitHub to a container registry to the VM) in place of the local rebuild button, alerts on VM health, the client portal.

## Things that will need code changes

- CORE's rebuild button assumes A.C.O.R.N builds on the same machine. In Azure the build moves to a pipeline, or CORE is told to build on the other VM.
- CORE's AI shim path (above).
- The application database account (non-superuser) and the connection settings.
- A.C.O.R.N's allowed web origin and the public address settings.

## Effort

About 2 to 4 days for Phases 1 to 3 if nothing surprising turns up; add a few days for parallel running. The pipeline, Entra sign-in and portal are separate pieces of work after that.

## Risks

- The AI path (above): unresolved.
- A restore that is only checked by reading, not run: rehearse the restore once before cut-over.
- A signed-in desktop on a VM is fragile: set auto-logon and a scheduled check that CORE is running.
- The data stores restored from a volume copy must be tested, not assumed.

## Later (recorded, not started)

- Save all the API information for the integrated tools as a skill for Leafy and for JAX.
- Teach JAX the way Leafy was taught about HaloPSA: JAX should know every integrated tool and what it can read.

## Decisions (2026-10-30)

- **AI path:** try the normal Claude plan first (Claude Code signed in on the CORE VM); move to an API key if that is not allowed or does not hold up.
- **Access:** NinjaOne remote session now; NordLayer or Tailscale later; public HTTPS for the client portal only, long term.
- **Region:** Central US. The step-by-step is in `docs/AZURE_RUNBOOK.md`; `infra/azure/deploy.ps1` previews by default and creates nothing until run with `-Deploy`.

## What I need from you

1. The AI path decision (API key, Azure's model service, or check the plan terms first).
2. RMM or Tailscale for reaching the machines.
3. The region.
4. When the credit expires exactly, from the billing page.

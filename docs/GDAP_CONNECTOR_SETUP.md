# GDAP Microsoft connector: setup plan (not started)

Status: planned, nothing built or created yet. Saved 2026-10-27. Read "What clients will see" before doing Part 5.

**Update (2026-10-27, after a deep read of CIPP's API; see `docs/CIPP_CAPABILITIES.md` in the CORE repo):** CIPP already reads DLP, sensitivity labels, PIM role policies, mailbox rules, forwarding, OAuth apps and more, and has about 290 action functions (reset password, revoke sessions, block sign-in, remove a mailbox rule, contain a compromised user in one call). It acts through its own app, which is already consented in every client tenant. So Parts 3 and 5 (a second app and consenting it in each client) are only needed for something CIPP cannot do; the access reviews read (`AccessReview.Read.All`) and SharePoint tenant settings are the two known gaps in CIPP's read permissions. Playbook actions should go through CIPP first.

Goal: read more Microsoft 365 data than CIPP exposes (to answer the 34 client-review Microsoft questions CIPP does not cover), and let playbooks run write actions (reset password, revoke sessions, disable account, delete a message, disable a mailbox rule) under the Autonomy guardrails.

## What clients will see (decide this before Part 5)

Granting an app's permissions in a client tenant creates an **enterprise application** (service principal) there. It is **not invisible**:

- Client admins see it under Entra admin center → Enterprise applications, with the name we give the app.
- The consent appears in the client's audit log.
- Actions taken through it show in the client's audit and sign-in logs (partner delegated activity appears under GDAP either way).

Ways to avoid confusion:

1. **Name the apps plainly,** for example "Live Oak IT Partners - Security Monitoring" (read) and "Live Oak IT Partners - Security Response" (actions), with a logo and a homepage URL that explains them. Put the same text in the app registration's description.
2. **Tell clients first** (one paragraph in a QBR or an email: "you will see this app; it is how we monitor and respond; remove it and we lose X").
3. **Reuse an app that is already there.** CIPP's own app is already in each client tenant, so using it adds nothing visible. The cost: it only has the permissions CIPP was given, so most of the 34 gap questions stay unanswered.
4. **Consent in stages:** start with a few of your own and friendly clients, then roll out.

## Part 1: GDAP roles (Partner Center)

| Account | Used for | GDAP roles |
|---|---|---|
| `acorn-read` | all reading, always on | Global Reader, Security Reader, Exchange Administrator, Teams Administrator |
| `acorn-action` | automated and approved actions only | User Administrator (or Helpdesk Administrator), Exchange Administrator |

Both are normal partner-tenant users in a security group that holds those GDAP roles for your clients. Give each a recoverable MFA method. Do not use a person's own account.

## Part 2: Read app (partner tenant, Entra admin center)

1. App registrations → New registration: `A.C.O.R.N Reader` (use the client-facing name from above). Accounts in any organizational directory (multitenant). No redirect URI.
2. Authentication → Allow public client flows: Yes (for the one-time device-code sign-in).
3. API permissions, all delegated:
   - Microsoft Graph: Directory.Read.All, Policy.Read.All, User.Read.All, Application.Read.All, AuditLog.Read.All, Reports.Read.All, RoleManagement.Read.Directory, RoleManagementPolicy.Read.Directory, AccessReview.Read.All, IdentityRiskyUser.Read.All, IdentityRiskEvent.Read.All, SecurityAlert.Read.All, SecurityIncident.Read.All, DeviceManagementManagedDevices.Read.All, DelegatedPermissionGrant.Read.All, InformationProtectionPolicy.Read.All, SharePointTenantSettings.Read.All, UserAuthenticationMethod.Read.All
   - Office 365 Exchange Online: Exchange.Manage
   - Skype and Teams Tenant Admin API: user_impersonation
4. Grant admin consent for your own tenant.
5. Certificates & secrets → New client secret, 24 months. Copy the value.

(Exact permission names to be confirmed when the connector is built; a consent error may mean one needs adjusting.)

## Part 3: Action app

A second registration (`A.C.O.R.N Actions`), same multitenant and public-client settings. Delegated permissions: User.ReadWrite.All, User.RevokeSessions.All, UserAuthenticationMethod.ReadWrite.All, Mail.ReadWrite, MailboxSettings.ReadWrite, Exchange.Manage (Office 365 Exchange Online). Kept separate so the write token is only used when a playbook or an approved action asks for it.

## Part 4: Where the details go

Never in chat. Enter in a CORE connector screen (to be built): partner tenant ID, read app client ID and secret, action app client ID and secret. Then two one-time device-code sign-ins (`acorn-read` for the read app, `acorn-action` for the action app); CORE stores and keeps the refresh tokens alive.

## Part 5: Consent in each client tenant

The connector does it, with one run by a user who holds Global Administrator through GDAP (a separate one-time sign-in; the token is not kept). New clients are consented automatically afterwards. **This is the step that makes the app appear in client tenants.**

## Part 6: Turning on automatic actions

Settings → Autonomy guardrails. Start in dry-run mode (playbooks log what they would do). Choose the clients that may have automatic actions (default: opt-in per client). Fill in the protected-accounts list (break-glass admins, your team, executives). Per-action thresholds decide what runs unattended and what waits for approval. Proposed ratings: revoke sessions and disable a mailbox rule low; reset password and delete a message medium; disable an account high.

## Guardrails to build with the actions

Per-client rate cap, protected accounts, dry-run mode, an audit entry per action, a kill switch, and a recorded way to undo where Graph allows (re-enable an account; password resets and deleted messages cannot be undone).

## Build order

1. Setup screen, sign-in, auto-consent.
2. Graph reads, wired into the client review (Microsoft section answers).
3. Exchange reads, then Teams reads.
4. Write actions behind the existing action types (`disable_user`, `reset_password`, plus session, message and rule actions), dry-run first.

## The 34 questions this would add answers for

Client review, Microsoft 365 section: 99 questions, 65 answered today from CIPP checks. Graph about 8 to 10 (self-service password reset, access reviews x2, PIM approval x2, sensitivity labels, emergency accounts partly, some SharePoint sharing); Exchange about 3 to 4 (mailbox audit actions, priority accounts x2, emergency-account monitoring partly); Teams 11; DLP 2 (Purview); 4 live only in admin-center settings and are not reachable.

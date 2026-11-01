# Sign in with Microsoft

People sign in to A.C.O.R.N with their Microsoft work account. Only members of one security group may sign in. Someone with no A.C.O.R.N account yet gets one on first sign-in, as a **Viewer**; an administrator raises the role in Settings > Workspace.

## What you need first

1. **A web address that starts with `https://`** for A.C.O.R.N, with a real certificate. Microsoft refuses any other redirect address except `localhost`. Until A.C.O.R.N has one, do not start this.
2. Rights in the Microsoft tenant to register an app and to create a security group.

## 1. Register the app (Entra admin center)

1. Entra ID > App registrations > New registration. Name: `A.C.O.R.N`. Supported account types: **this organizational directory only**.
2. Redirect URI, platform **Web**: `https://<your address>/api/v1/auth/sso/microsoft/callback`.
3. Copy the **Application (client) ID** and the **Directory (tenant) ID**.
4. Certificates & secrets > New client secret. Copy the **Value** now (it is shown once). Put a reminder in the calendar before it expires; sign-in stops working when it does.
5. API permissions: the default `User.Read` is enough. Nothing needs admin consent.

## 2. Make the group

1. Entra ID > Groups > New group. Type **Security**. Name it, for example, `ACORN-Users`. Add the people.
2. Copy its **Object ID**.
3. Recommended: Enterprise applications > A.C.O.R.N > Properties > **Assignment required = Yes**, then assign the group. Microsoft then refuses everyone else before A.C.O.R.N is even asked. A.C.O.R.N checks the group itself as well.

## 3. Settings on the A.C.O.R.N server

Add to `/srv/acorn/AiSOC/.env`, then run the Update button (or `docker compose up -d`):

| Setting | Meaning |
| --- | --- |
| `MS_SSO_TENANT_ID` | Directory (tenant) ID |
| `MS_SSO_CLIENT_ID` | Application (client) ID |
| `MS_SSO_CLIENT_SECRET` | the secret Value |
| `MS_SSO_REDIRECT_URI` | the exact address from step 1.2 |
| `MS_SSO_GROUP_ID` | the group's Object ID (strongly recommended; without it anyone in your Microsoft tenant can sign in) |
| `MS_SSO_ACORN_TENANT_ID` | the A.C.O.R.N workspace new people are added to (Settings > Workspace shows its id) |
| `MS_SSO_NEW_USER_ROLE` | role a first sign-in starts with; default `viewer`. Administrator roles are never given automatically |
| `MS_SSO_PASSWORD_LOGIN` | `admins` (default): only administrators can still use a password. `all`: everyone can |
| `MS_SSO_WEB_URL` | only if the sign-in page is on a different address from the redirect |

If the first four are empty the button does not appear and nothing changes.

## How it behaves

- People are recognised by Microsoft's permanent id for them, not by email, so a changed or reused address cannot take over someone else's account.
- The first time, an existing account with the same Microsoft user name and no link yet is linked. Otherwise a Viewer is created.
- A turned-off account stays refused.
- If a person is in too many groups for Microsoft to list them, sign-in is refused (it fails closed) rather than guessing.
- Taking someone out of the group stops new sign-ins; a session already open ends when its token expires.
- Each sign-in, link and creation is written to the audit log.

## Safety net

With `MS_SSO_PASSWORD_LOGIN=admins`, administrators keep their account name and password as a way back in if Microsoft or the secret has a problem. Other roles are Microsoft-only, and there is no page yet where a person changes their own password. Keep at least one administrator with a password you know works.

## If it does not work

The sign-in page says why in plain words (not in the group, no account, turned off, wrong organization, took too long). The server log lines start with `sso.`.

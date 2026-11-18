# Google Workspace access for A.C.O.R.N (business email compromise scan and detected apps)

Roadmap items: `google-bec-scan` (read mail for business email compromise) and `r7-ai-34` (detected applications from Google Workspace). Nothing is built until step 1 to 4 are done for one friendly client. It is read-only: A.C.O.R.N never sends, deletes or changes mail.

## What you set up once (Live Oak, in Google Cloud)

1. Sign in at https://console.cloud.google.com with a Live Oak Google account. Create a project named `acorn-google-read` (Select a project, New project).
2. In that project open APIs and Services, Library, and enable: **Gmail API**, **Admin SDK API**.
3. Open IAM and Admin, Service Accounts, Create service account, name `acorn-reader`. Skip the optional role steps. Open the account, Keys, Add key, Create new key, JSON. Keep that file private: do not e-mail it, do not paste it in chat. It goes into the A.C.O.R.N server secret store (tell me when you have it and I will say how to hand it over).
4. Open the service account details and copy its **Client ID** (a long number). You need it for each client.

## What each client's Google admin does (per client, 5 minutes)

The client's Google Workspace super admin does this in https://admin.google.com:

1. Security, Access and data control, API controls, **Manage Domain Wide Delegation**, Add new.
2. Client ID: the number from step 4 above.
3. OAuth scopes (comma separated, nothing more):
   - `https://www.googleapis.com/auth/gmail.readonly` (read mail, BEC scan)
   - `https://www.googleapis.com/auth/admin.directory.user.readonly` (list the users to scan)
   - `https://www.googleapis.com/auth/admin.directory.user.security` (apps people authorized, for detected applications)
4. Authorize.

You, as the MSP, send the client the three scope lines above and the Client ID. The client should agree in writing that Live Oak reads mail for security monitoring (this is a privacy matter; add it to the client's security addendum).

## What I then build

* CORE reads each client mailbox's recent mail headers (sender, reply-to, forwarding rules, new inbox rules, login changes) and looks for the BEC signs: a rule that forwards or deletes mail, a reply-to that differs from the sender, a payment request from a lookalike domain.
* Results arrive in A.C.O.R.N as alerts for that client. Mail bodies are not stored, only the finding and the message id.
* Detected applications come from the same service account (apps authorized per user) and fill Compliance, Vendors, detected applications.

## What I need from you to start

Reply in the box on `google-bec-scan` with the first client's name and tell me when steps 1 to 4 and the client's steps are done. Never send me the JSON key.

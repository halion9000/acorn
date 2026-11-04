# A public address for honeytokens

Why: a planted link only alerts if the machine that opens it can reach A.C.O.R.N. Today the address is `acorn.goliveoak.com`, which works only on the network or VPN. A planted file that leaves the network (stolen laptop, a copy opened at home) cannot call back. This sets up a second name, for example `canary.goliveoak.com`, that reaches **only** the tripwire path and nothing else.

What the server already has (deployed): a listener on the server's internal network that answers `/api/v1/canary/<token id>` and returns 404 for every other path (checked: `/`, `/api/v1/health`, `/api/v1/alerts`, and the tripwire path with extra text all give 404), and a `cloudflared` service that connects out to Cloudflare, so no port is opened to the internet. It replaces any visitor-supplied address header with the one Cloudflare saw, so the alert names the real visitor.

## The easy way: the "Cloudflare canary" card in CORE

1. In Cloudflare create the tunnel and copy its token (steps 1 to 3 below; the OS buttons on the install screen do not matter, install nothing).
2. In CORE open the connector settings, find the **Cloudflare canary** card, paste the token and press Save. To change it later, paste a new one.
3. CORE sends it to A.C.O.R.N (checked there: it must be a real tunnel token; it is never shown again). The next A.C.O.R.N update, from CORE's rebuild button or A.C.O.R.N's Update button, puts it into `.env`, adds `cloudflared` to `ACORN_EXTRAS`, sets `ACORN_CANARY_URL` to `https://canary.goliveoak.com` if none is set, and starts the tunnel. An update with no new code still applies a new token.
4. Check it as in step 6 below. The change is in the audit log as `honeytokens:tunnel_token_changed` (without the token).

The manual steps below do the same by hand and still work.

## Steps by hand (about 15 minutes)

1. In the Cloudflare dashboard open **Zero Trust**, then **Networks**, then **Tunnels**, then **Create a tunnel**, choose **Cloudflared**, name it `acorn-canary`.
2. On the "Install connector" screen, copy the **token** (the long text after `--token` in the command shown). Do not run the command it shows; the server runs the connector itself. Treat the token like a password.
3. Click **Next**, then add a **Public hostname**: subdomain `canary`, domain `goliveoak.com`, service type **HTTP**, URL `caddy:8088`. Save the tunnel.
4. On the A.C.O.R.N server (`liveoak-acorn-vm`), edit `/srv/acorn/AiSOC/.env` and add these three lines (replace the token text):

```text
CLOUDFLARED_TUNNEL_TOKEN=paste-the-token-here
ACORN_CANARY_URL=https://canary.goliveoak.com
ACORN_EXTRAS="honeytokens cloudflared"
```

   If `ACORN_EXTRAS` is already there, add `cloudflared` to its list instead of a second line.
5. Run the normal update (the same one used for every deploy). It starts the tunnel and restarts honeytokens with the new address.
6. Check it: from a phone on mobile data (not the VPN) open `https://canary.goliveoak.com/` (it should say "Not found"), then check Zero Trust, Networks, Tunnels shows `acorn-canary` as **Healthy**.

## Using it

- **New** honeytokens made after step 5 carry the new address. Tokens made earlier keep the old address: create new ones and plant those, then retire the old ones.
- The real test: make a spare Link token, open its link from the phone on mobile data. The token should turn to triggered and an alert should appear. The trigger's **Source IP** on the token page should be the phone's public address. If it shows an internal address (10.x, 172.x) instead, tell me: the header that carries the visitor's address is the part I could only test with a stand-in.

## What this exposes

One path pattern, `/api/v1/canary/<id>`, which accepts a visit and records it. The rate limits already on that route (per token and overall) apply. Nothing else on the server is reachable through this name, and the tunnel token can be revoked in Cloudflare at any time.

NOT VERIFIED end to end: the tunnel itself (needs your Cloudflare token). Verified: the listener's routing and the replaced address header, run against a stand-in backend.

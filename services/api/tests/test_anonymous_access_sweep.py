"""In production, NO route answers an anonymous request except an explicit public list.

Found by sending an anonymous request to every route of a production-mode API:
about 35 answered, including writes (deployment config, air-gap bundles, STIX
indicator creation, compliance evidence collection) and LLM-backed endpoints
anyone could use to spend the owner's LLM budget. The API has no global login
check: each handler must opt in, and many never did.

This test is the net under all of it: it probes every route in the OpenAPI
schema with NO credentials, in production mode, and fails for any route that is
not on PUBLIC below. To make a new route public you must add it here, with a
reason, where a reviewer will see it.
"""

import asyncio
import re

import httpx
import pytest
from app.api.v1 import deps
from app.main import app

UUID = "00000000-0000-0000-0000-0000000000aa"
BODY_METHODS = {"POST", "PUT", "PATCH"}

# (METHOD, path template) -> why anonymous callers are allowed.
PUBLIC = {
    (
        "GET",
        "/api/v1/public/client-status/{token}",
    ): "the client status page opened by a private link: the secret is the credential (only its hash is stored), every problem is the same 404, and it returns client-safe counts only",
    ("POST", "/api/v1/auth/login"): "sign-in",
    ("POST", "/api/v1/auth/refresh"): "token refresh (the refresh token is the credential)",
    ("GET", "/auth/oidc/login"): "SSO flow (fails closed with 501 when unconfigured)",
    ("GET", "/auth/oidc/callback"): "SSO flow",
    ("GET", "/auth/oidc/logout"): "SSO flow",
    ("GET", "/auth/saml/login"): "SSO flow (fails closed with 501 when unconfigured)",
    ("POST", "/auth/saml/acs"): "SSO flow",
    ("GET", "/auth/saml/logout"): "SSO flow",
    ("GET", "/auth/saml/metadata"): "SAML service-provider metadata is public by design",
    ("GET", "/health"): "container health check",
    ("GET", "/api/v1/health"): "reachability probe for the web console",
    ("GET", "/api/v1/oauth/callback"): "OAuth redirect target (validates its own state)",
    ("GET", "/api/v1/auth/sso/status"): "tells the sign-in page whether to show Sign in with Microsoft (no data)",
    ("GET", "/api/v1/auth/sso/microsoft/login"): "starts Microsoft sign-in (fails closed with 501 when unconfigured)",
    ("GET", "/api/v1/auth/sso/microsoft/callback"): "Microsoft redirect target (verifies state, id token and group itself)",
    ("POST", "/api/v1/auth/sso/exchange"): "one-time code from the callback becomes tokens (the code is the credential)",
    ("POST", "/api/v1/passkeys/authenticate/begin"): "passkey sign-in",
    ("POST", "/api/v1/passkeys/authenticate/finish"): "passkey sign-in",
    ("GET", "/api/v1/push/public-key"): "VAPID public key is public by design",
    ("GET", "/api/v1/r/{slug}"): "public share links for replays",
    ("POST", "/api/v1/waitlist/signup"): "public marketing signup",
    ("POST", "/api/v1/inbox/itsm/{tenant_token}/{connector_instance_id}"): (
        "inbound ITSM webhook: authenticated by the secret tenant_token in the URL plus the "
        "vendor signature, and answers 401 on a mismatch (the 500 here is only the fake database)"
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/status"): (
        "CORE's per-run report: authenticated by the secret core-feed token in the URL (only an active token with the core-feed label is accepted; "
        "anything else is a 401 in the handler), and it can only write that tenant's own core_feed rows (the 422 here is the empty body)"
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/closed"): (
        "CORE's closed-incident report: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it can only resolve that tenant's own alerts "
        "that are still new, matched on the incident id (the 422 here is the empty body)"
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/clients"): (
        "CORE's list of a vendor's clients: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it can only add or rename that tenant's own client-mapping rows (the 422 here is the empty body)"
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/tickets"): (
        "CORE's list of the PSA tickets linked to open incidents: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it can only add ticket details to that feed's own alerts (the 422 here is the empty body)"
    ),
    ("GET", "/api/v1/canary/{token_id}"): (
        "The honeytoken tripwire: a planted link must work for someone who has no AiSOC account, so it cannot require sign-in. It answers every id the same way (a one pixel image), forwards only a well-formed UUID, is rate limited per token and overall, and returns nothing about the token"
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/device-names"): (
        "CORE's names for the devices vendor incidents were raised on: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it can only fill an EMPTY host list on that feed's own alerts (the 422 here is the empty body)"
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/entities"): (
        "CORE's user, host and address for vendor findings, read from the vendor's own evidence: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it can only fill EMPTY user, host and address lists on that feed's own alerts (the 422 here is the empty body)"
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/remote-tools"): (
        "CORE's remote tools: the matches of a scan of one client's devices against the tool catalog. Authenticated by the core-feed token in the path, checked in the handler (401 without it); can only add or replace remote-tool sightings under that feed's own mapped client tenants, and an unmapped client stores nothing"
    ),
    ("GET", "/api/v1/inbox/core-feed/{tenant_token}/remote-tools/catalog"): (
        "The remote tool catalog (names and patterns, no client data) for CORE to match against: authenticated by the core-feed token in the path, checked in the handler (401 without it)"
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/devices"): (
        "CORE's list of a tool's devices: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it can only add or update devices under that feed's own client tenants, and only for clients already mapped (the 422 here is the empty body)"
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/identities"): (
        "CORE's list of the people each tool knows (Datto SaaS Protection, Dropsuite, Huntress, Huntress SAT, HaloPSA): authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it can only add or update people under that feed's own client tenants, and only for clients already mapped (the 422 here is the empty body)"
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/detected-applications"): (
        "CORE's list of the apps found in a client's Microsoft 365 tenant: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it can only add or update detected applications under that feed's own client tenants",
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/canary-tunnel"): (
        "CORE's Cloudflare canary card sends its tunnel token here: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); the token is checked, kept for the update script and never echoed, and a change is audited without it (the 422 here is the empty body)"
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/directory-audits"): (
        "CORE's identity-related directory audit entries read through CIPP: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it can only add entries under that feed's own client tenants, and only for clients already mapped (the 422 here is the empty body)"
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/cipp-actions"): (
        "CORE's report of the rules and audit lines of the actions it can take through CIPP (never a credential): authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it can only replace that feed's own organization's report, and nothing it holds can change a rule or run an action",
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/secureframe"): (
        "CORE's report of Secureframe's control tests (counts, failing tests with their owner, number of risks and policies; never a credential, policy text or evidence): authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it can only replace that feed's own organization's report"
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/client-documents"): (
        "CORE's read-only copy of a client's IT Glue documentation (documents, runbooks, configurations, locations, and password entries as a name and link only, never the password): authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it can only add or update records under that feed's own client tenants, and text that looks like a secret is blanked on arrival",
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/person-tickets"): (
        "CORE's list of each person's recent HaloPSA tickets: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it can only add or update tickets under that feed's own client tenants, and only for clients already mapped (the 422 here is the empty body)"
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/finance"): (
        "CORE's daily snapshot of HaloPSA's recurring invoices and owed invoices: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it replaces only that organization's own snapshot, which only people with the finance permissions can read."
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/vendor-costs"): (
        "CORE's daily summary of what each software vendor billed per month (vendor name and amount, no invoice detail), read from QuickBooks: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it replaces only that organization's own bills for the months sent.",
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/profit-tickets"): (
        "CORE's daily list of the tickets each client's HaloPSA hours in one month went on (ticket number, subject, hours, who): authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it replaces only that organization's own list for the month sent.",
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/pnl"): (
        "CORE's daily copy of QuickBooks' profit and loss, line by line per month (account names and amounts, no customer or vendor detail): authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it replaces only that organization's own lines for the months sent, readable only with the finance permissions.",
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/qbo-sales"): (
        "CORE's daily copy of QuickBooks' sales by customer per month (customer name and amount): authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it replaces only that organization's own amounts for the months sent, readable only with the finance permissions.",
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/books"): (
        "CORE's daily summary of QuickBooks' monthly costs (one amount per cost category per month, no vendor or customer detail): authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it replaces only that organization's own QuickBooks cost entries for the months sent, and never a typed one.",
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/ticket-stats"): (
        "CORE's daily summary of HaloPSA ticket statistics (counts per client per month and what is open, no ticket text): authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it replaces only that organization's own summary."
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/csat"): (
        "CORE's daily summary of SimpleSat customer satisfaction responses (counts per company per month and each company's newest comments): authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it replaces only that organization's own summary."
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/metric-staff-weekly"): (
        "CORE's daily weekly facts per engineer (team, hours, utilization, days off, tickets closed and updated, calls, survey scores): authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it replaces only that organization's own dataset."
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/metric-ticket-detail"): (
        "CORE's daily weekly ticket facts (counts by client, type, category and priority, resolution time, stale tickets; no ticket text beyond a title): authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it replaces only that organization's own dataset."
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/metric-invoice-lines"): (
        "CORE's daily invoiced amounts per client per month per invoice line: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it replaces only that organization's own dataset."
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/metric-dialpad-weekly"): (
        "CORE's daily Dialpad call counts and call time per engineer per week: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it replaces only that organization's own dataset."
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/metric-m365-roles"): (
        "CORE's daily Microsoft 365 directory roles and their members per client: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it replaces only that organization's own dataset."
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/profitability"): (
        "CORE's daily summary of HaloPSA's invoiced revenue per client per month, hours worked and agents: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it replaces only that organization's own summary, readable only with the finance permissions."
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/ninja-deploy-options"): (
        "CORE's list of the NinjaOne roles, organizations and locations the Devices page can offer when it installs the agent (names and numeric ids only, no key or link): authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it replaces only that organization's own list.",
    ),
    ("GET", "/api/v1/inbox/core-feed/{tenant_token}/risk-tickets"): (
        "The HaloPSA ticket numbers opened from Client Risk Score questions that CORE should read the status of (numbers only, no client or question): authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it reads only that feed's own clients."
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/risk-tickets/status"): (
        "CORE's read of those tickets' status names from HaloPSA: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it can only update the status of tickets already opened from a question under that feed's own clients."
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/vulnerabilities"): (
        "CORE's list of each client's vulnerabilities, one line each: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it can only write under that feed's own client tenants, and only for accounts already mapped to a client."
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/mfa-users"): (
        "CORE's multi-factor status per person read through CIPP: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it can only write under that feed's own client tenants, and only for clients already mapped (the 422 here is the empty body)"
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/scripts"): (
        "CORE's list of the scripts its owner switched on, for the Run script button: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it can only store that tenant's own script list (the 422 here is the empty body)"
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/m365-checks"): (
        "CORE's Microsoft 365 baseline checks per client, read through CIPP: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it can only write under that feed's own client tenants",
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/license-counts"): (
        "CORE's daily counts of what each tool covers for a client (licences, machines, people): authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it can only write under that feed's own client tenants, and only for clients already mapped (the 422 here is the empty body)",
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/sweep-runs"): (
        "CORE's latest pass of each per-client sweep (how many clients it reached): authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it can only write that feed's own run records (the 422 here is the empty body)",
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/tools"): (
        "CORE's list of which of the owner's tools are connected in CORE (name, one line, connected or not; never a credential): authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it can only replace that feed's own list of tools (the 422 here is the empty body)"
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/vcio-reviews"): (
        "CORE's daily summary of a client's vCIO Toolbox recommendations and risks: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it can only write under that feed's own client tenants, and only for clients already mapped (the 422 here is the empty body)"
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/vcio-proposals/approved"): (
        "CORE collecting the vCIO Toolbox suggestions a person approved: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it reads only that feed's own client tenants and changes nothing"
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/vcio-proposals/{proposal_id}/result"): (
        "CORE reporting whether vCIO Toolbox took an approved suggestion: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it can only answer an approved suggestion of that feed's own client tenants, once (the 422 here is the empty body)"
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/secure-scores"): (
        "CORE's Microsoft Secure Score per client read through CIPP: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it can only write under that feed's own client tenants, and only for clients already mapped (the 422 here is the empty body)"
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/signins"): (
        "CORE's sign-ins read through CIPP: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it can only add sign-ins under that feed's own client tenants, and only for clients already mapped (the 422 here is the empty body)"
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/state"): (
        "CORE's open-incident state report: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); it can only write that tenant's own alerts' vendor state (the 422 here is the empty body)"
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/actions/claim"): (
        "CORE collects the vendor actions analysts queued: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); only that tenant's pending actions, each handed out once (the 422 here is the empty body)"
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/sync-requests/claim"): (
        "CORE collects the Sync requests analysts made on the Connectors page: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); only that tenant's own pending requests, each handed out once (the 422 here is the empty body)"
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/actions/{action_id}/result"): (
        "CORE reports how a claimed vendor action went: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); only a claimed action of that tenant can be answered (the 422 here is the empty body)"
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/bec/{case_id}/progress"): (
        "CORE reports how far a business email compromise search has got: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); only an open case of that tenant's scope can be updated (the 422 here is the empty body)"
    ),
    ("POST", "/api/v1/inbox/core-feed/{tenant_token}/bec/{case_id}/result"): (
        "CORE hands over a finished business email compromise report: authenticated by the secret core-feed token in the URL (401 in the handler otherwise); only an open case of that tenant's scope can be answered, once (the 422 here is the empty body)"
    ),
}


def _all_routes() -> list[tuple[str, str]]:
    return sorted(
        (m.upper(), p) for p, ops in app.openapi()["paths"].items() for m in ops if m in ("get", "post", "put", "patch", "delete")
    )


async def _status(client: httpx.AsyncClient, method: str, path: str):
    url = re.sub(r"\{[^}]+\}", UUID, path)

    async def ask(timeout: float):
        r = await asyncio.wait_for(client.request(method, url, json={} if method in BODY_METHODS else None), timeout=timeout)
        return r.status_code

    try:
        try:
            # All routes are asked at once, so on a busy machine a route that WILL refuse can miss a short deadline. A timeout is only believed once the route has been
            # asked again with a longer one, by when the rest of the sweep is done: a route that really streams still times out then.
            return await ask(6)
        except TimeoutError:
            return await ask(20)
    except TimeoutError:
        return "kept the connection open (streaming) without credentials"
    except Exception as exc:  # a route that blows up without credentials has not refused them
        return f"error: {type(exc).__name__}"


async def _sweep() -> dict[tuple[str, str], object]:
    async def fake_db():
        yield None  # a guarded route must refuse BEFORE touching the database

    app.dependency_overrides[deps.get_db] = fake_db
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            routes = _all_routes()
            results = await asyncio.gather(*[_status(client, m, p) for m, p in routes])
            return dict(zip(routes, results, strict=False))
    finally:
        app.dependency_overrides.pop(deps.get_db, None)


@pytest.fixture
def production(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(deps, "is_dev_mode", lambda: False)
    # /metrics decides from the cached settings value; in a real production process it refuses
    monkeypatch.setattr(main_module, "_metrics_environment_is_dev", lambda: False)


def test_the_sweep_sees_the_whole_api():
    assert len(_all_routes()) > 350, "the OpenAPI schema is incomplete: the sweep would prove nothing"


def test_only_the_documented_public_routes_answer_without_credentials(production):
    results = asyncio.run(_sweep())
    exposed = sorted(f"{m:6} {p}  -> {status}" for (m, p), status in results.items() if status not in (401, 403) and (m, p) not in PUBLIC)
    assert not exposed, (
        f"{len(exposed)} route(s) answered an ANONYMOUS request in production. Add a login/permission "
        "dependency, or (only if it is truly public) add it to PUBLIC with a reason:\n  " + "\n  ".join(exposed)
    )


def test_every_public_entry_is_a_real_route():
    routes = set(_all_routes())
    stale = sorted(f"{m} {p}" for (m, p) in PUBLIC if (m, p) not in routes)
    assert not stale, f"PUBLIC lists routes that no longer exist (remove them): {stale}"

"""Naming the service that sent a batch of mail, from the domains it used to authenticate (the SPF and DKIM domains in a DMARC report).

A report says which address sent and which domains vouched for it; it does not say whose service that is. The well-known mail and marketing services sign with their own domains, so a domain list is
enough to name most of what a company sends. What is not on the list stays "Unknown", with its address, so a person can look it up; nothing is guessed.
"""

from __future__ import annotations

import ipaddress
import json
from collections import Counter
from typing import Any

# (a domain the service signs with or sends from, the name to show). A domain matches itself and every subdomain of it. First match wins, so more specific entries come first.
KNOWN_SENDERS: tuple[tuple[str, str], ...] = (
    ("spf.protection.outlook.com", "Microsoft 365"),
    ("protection.outlook.com", "Microsoft 365"),
    ("outlook.com", "Microsoft 365"),
    ("onmicrosoft.com", "Microsoft 365"),
    ("microsoftonline.com", "Microsoft 365"),
    ("_spf.google.com", "Google Workspace"),
    ("google.com", "Google Workspace"),
    ("googlemail.com", "Google Workspace"),
    ("gmail.com", "Google Workspace"),
    ("sendgrid.net", "SendGrid"),
    ("sendgrid.com", "SendGrid"),
    ("mailchimp.com", "Mailchimp"),
    ("mcsv.net", "Mailchimp"),
    ("mailchimpapp.net", "Mailchimp"),
    ("rsgsv.net", "Mailchimp"),
    ("mandrillapp.com", "Mandrill (Mailchimp)"),
    ("amazonses.com", "Amazon SES"),
    ("hubspotemail.net", "HubSpot"),
    ("hubspot.com", "HubSpot"),
    ("hs-send.com", "HubSpot"),
    ("salesforce.com", "Salesforce"),
    ("exacttarget.com", "Salesforce Marketing Cloud"),
    ("zendesk.com", "Zendesk"),
    ("freshdesk.com", "Freshdesk"),
    ("freshworks.com", "Freshworks"),
    ("constantcontact.com", "Constant Contact"),
    ("ctctcdn.com", "Constant Contact"),
    ("mailgun.org", "Mailgun"),
    ("mailgun.com", "Mailgun"),
    ("sparkpostmail.com", "SparkPost"),
    ("postmarkapp.com", "Postmark"),
    ("pm-bounces.com", "Postmark"),
    ("haloservicedesk.com", "HaloPSA"),
    ("halopsa.com", "HaloPSA"),
    ("intuit.com", "Intuit (QuickBooks)"),
    ("quickbooks.com", "Intuit (QuickBooks)"),
    ("docusign.net", "DocuSign"),
    ("docusign.com", "DocuSign"),
    ("atlassian.net", "Atlassian"),
    ("atlassian.com", "Atlassian"),
    ("zoho.com", "Zoho"),
    ("zohomail.com", "Zoho"),
    ("proofpoint.com", "Proofpoint"),
    ("pphosted.com", "Proofpoint"),
    ("mimecast.com", "Mimecast"),
    ("mimecast-offshore.com", "Mimecast"),
    ("barracudanetworks.com", "Barracuda"),
    ("knowbe4.com", "KnowBe4"),
    ("cisco.com", "Cisco"),
    ("ironscales.com", "Ironscales"),
    ("slack.com", "Slack"),
    ("github.com", "GitHub"),
    ("linkedin.com", "LinkedIn"),
    ("facebookmail.com", "Facebook"),
    ("paypal.com", "PayPal"),
    ("stripe.com", "Stripe"),
    ("shopify.com", "Shopify"),
    ("squarespace.com", "Squarespace"),
    ("wix.com", "Wix"),
    ("godaddy.com", "GoDaddy"),
    ("secureserver.net", "GoDaddy"),
    ("ovh.net", "OVH"),
    ("emailsrvr.com", "Rackspace"),
)


def _matches(domain: str, known: str) -> bool:
    return domain == known or domain.endswith("." + known)


def identify_sender(spf_domains: list[str], dkim_domains: list[str]) -> str | None:
    """The service's name, or None when none of the authenticating domains is a known service. SPF domains are tried before DKIM ones (they name where the mail left from)."""
    for domain in [d.strip().lower().rstrip(".") for d in [*spf_domains, *dkim_domains] if d]:
        for known, name in KNOWN_SENDERS:
            if _matches(domain, known):
                return name
    return None


# Address ranges whose owner is public and stable. A sender that signs with no known domain (mail passed on by Microsoft or Google, or sent with their servers) is still named from its address. The names say
# "mail servers" because the address is the provider's, not proof of which customer of the provider sent the mail.
KNOWN_NETWORKS: tuple[tuple[str, str], ...] = (
    ("2a01:111::/32", "Microsoft 365 mail servers"),
    ("2603:1000::/24", "Microsoft 365 mail servers"),
    ("2603:1096::/32", "Microsoft 365 mail servers"),
    ("40.92.0.0/15", "Microsoft 365 mail servers"),
    ("40.107.0.0/16", "Microsoft 365 mail servers"),
    ("52.100.0.0/14", "Microsoft 365 mail servers"),
    ("104.47.0.0/17", "Microsoft 365 mail servers"),
    ("209.85.128.0/17", "Google mail servers"),
    ("74.125.0.0/16", "Google mail servers"),
    ("66.249.80.0/20", "Google mail servers"),
    ("2607:f8b0::/32", "Google mail servers"),
    ("2a00:1450::/32", "Google mail servers"),
    ("167.89.0.0/17", "SendGrid"),
    ("198.2.128.0/18", "Mailchimp"),
    ("205.201.128.0/20", "Mailchimp"),
    ("54.240.0.0/18", "Amazon SES"),
)
_NETWORKS = tuple((ipaddress.ip_network(n), name) for n, name in KNOWN_NETWORKS)


def identify_by_address(ip: str) -> str | None:
    """The provider that owns this sending address, from a short list of well-known ranges, or None (pure)."""
    try:
        addr = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        return None
    for net, name in _NETWORKS:
        if addr.version == net.version and addr in net:
            return name
    return None


def failure_causes(row: dict[str, Any], default_from: str = "") -> list[str]:
    """Why one source line failed DMARC, in plain words (pure). A line that passed has none. SPF and DKIM are each explained when they did not line up with the From domain: the receiver's result for the
    domain that was checked (fail, softfail, none...) or, when it passed, the fact that it passed for a DIFFERENT domain than the one the mail claims (which is what "not aligned" means)."""
    if row.get("pass"):
        return []
    from_domain = str(row.get("header_from") or default_from or "the From domain")
    out: list[str] = []
    for kind, label, aligned_key in (("spf", "SPF", "spf"), ("dkim", "DKIM", "dkim")):
        if row.get(aligned_key):
            continue
        domains = [d for d in (row.get(f"{kind}_domains") or []) if d]
        results = [r for r in (row.get(f"{kind}_results") or []) if r]
        if not domains:
            out.append("no DKIM signature" if kind == "dkim" else "no SPF result")
            continue
        bad = [(d, r) for d, r in zip(domains, results, strict=False) if r != "pass"]
        if bad:
            d, r = bad[0]
            out.append(f"{label} {r} for {d}")
        else:
            out.append(f"{label} passed for {domains[0]}, not for {from_domain} (not aligned)")
    return out


def _top(counter: Counter[str], n: int) -> list[str]:
    return [k for k, _ in counter.most_common(n) if k]


class SenderStats:
    """What one sender (a named service, or one address) did across the stored lines, for the detail a person opens: the domains it authenticated with, who it said it was, how it failed and why."""

    def __init__(self) -> None:
        self.spf: Counter[str] = Counter()
        self.dkim: Counter[str] = Counter()
        self.envelope: Counter[str] = Counter()
        self.header: Counter[str] = Counter()
        self.causes: Counter[str] = Counter()
        self.dispositions: Counter[str] = Counter()
        self.reasons: Counter[str] = Counter()
        self.ips: Counter[str] = Counter()
        self.spf_failed = self.dkim_failed = self.both_failed = 0

    def add(self, row: dict[str, Any], count: int, default_from: str = "") -> None:
        for d in row.get("spf_domains") or []:
            self.spf[d] += count
        for d in row.get("dkim_domains") or []:
            self.dkim[d] += count
        if row.get("envelope_from"):
            self.envelope[str(row["envelope_from"])] += count
        self.header[str(row.get("header_from") or default_from)] += count
        self.dispositions[str(row.get("disposition") or "none")] += count
        for r in str(row.get("reason") or "").split(","):
            if r:
                self.reasons[r] += count
        if row.get("ip"):
            self.ips[str(row["ip"])] += count
        if not row.get("pass"):
            for c in failure_causes(row, default_from):
                self.causes[c] += count
            spf_bad, dkim_bad = not row.get("spf"), not row.get("dkim")
            if spf_bad and dkim_bad:
                self.both_failed += count
            elif spf_bad:
                self.spf_failed += count
            elif dkim_bad:
                self.dkim_failed += count

    def detail(self) -> dict[str, Any]:
        return {
            "spf_domains": _top(self.spf, 5),
            "dkim_domains": _top(self.dkim, 5),
            "envelope_from": _top(self.envelope, 3),
            "header_from": _top(self.header, 3),
            "causes": [{"text": t, "count": c} for t, c in self.causes.most_common(5)],
            "spf_only_failed": self.spf_failed,
            "dkim_only_failed": self.dkim_failed,
            "both_failed": self.both_failed,
            "dispositions": dict(self.dispositions),
            "reasons": _top(self.reasons, 4),
            "addresses": _top(self.ips, 5),
        }


def parse_ip_rdap(body: bytes) -> str | None:
    """Who the registry says owns an address, from an RDAP IP record: the organization in its contacts, else the network's name (pure). None when it is not an RDAP record or names nobody."""
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    for entity in data.get("entities") or []:
        vcard = entity.get("vcardArray") if isinstance(entity, dict) else None
        if isinstance(vcard, list) and len(vcard) > 1 and isinstance(vcard[1], list):
            for item in vcard[1]:
                if isinstance(item, list) and len(item) > 3 and item[0] == "fn" and isinstance(item[3], str) and item[3].strip():
                    return item[3].strip()[:120]
    name = data.get("name")
    return name.strip()[:120] if isinstance(name, str) and name.strip() else None

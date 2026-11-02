"""Naming the service that sent a batch of mail, from the domains it used to authenticate (the SPF and DKIM domains in a DMARC report).

A report says which address sent and which domains vouched for it; it does not say whose service that is. The well-known mail and marketing services sign with their own domains, so a domain list is
enough to name most of what a company sends. What is not on the list stays "Unknown", with its address, so a person can look it up; nothing is guessed.
"""

from __future__ import annotations

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

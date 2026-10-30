"""Names for the tools and feeds an alert can come from, for pages that list them (the Executive Digest's top alert sources)."""

from __future__ import annotations

SOURCE_NAMES: dict[str, str] = {
    "halopsa": "HaloPSA",
    "ninjaone": "NinjaOne",
    "petra": "Petra",
    "huntress": "Huntress",
    "blumira": "Blumira",
    "addigy": "Addigy",
    "liongard": "Liongard",
    "threatmate": "ThreatMate",
    "fieldeffect": "Field Effect",
    "dnsfilter": "DNSFilter",
    "auvik": "Auvik",
    "unifi": "UniFi",
    "slide": "Slide",
    "timus": "Timus",
    "huntress-sat": "Huntress SAT",
    "itglue": "IT Glue",
    "meraki": "Cisco Meraki",
    "datto-bcdr": "Datto BCDR",
    "datto-saas": "Datto SaaS",
    "dropsuite": "Dropsuite",
    "autoelevate": "AutoElevate",
    "cipp": "CIPP",
    "screenconnect": "ScreenConnect",
    "vciotoolbox": "vCIO Toolbox",
    # Alerts A.C.O.R.N raises itself, and ones a person entered.
    "aisoc-checks": "A.C.O.R.N posture checks",
    "manual": "Entered by hand",
    "generic_json": "Generic JSON",
    "generic-json": "Generic JSON",
}


def source_label(key: str | None) -> str:
    """A readable name for a source key: a known tool by its proper name, anything else with its separators turned into spaces and each word capitalised ("some_feed" is "Some Feed").

    ``Generic Generic JSON`` (the name an old ingest path stored as the connector type) is "Generic JSON".
    """
    raw = (key or "").strip()
    if not raw:
        return "Unknown"
    if raw in SOURCE_NAMES:
        return SOURCE_NAMES[raw]
    words = raw.replace("_", " ").replace("-", " ").split()
    deduped = [w for i, w in enumerate(words) if i == 0 or w.lower() != words[i - 1].lower()]
    return " ".join(w if w.isupper() else w[:1].upper() + w[1:] for w in deduped)

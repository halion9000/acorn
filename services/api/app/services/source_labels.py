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


def is_generic_inbox(connector_type: str | None) -> bool:
    """Whether a stored connector type is the generic JSON inbox, however it was written ("Generic Generic JSON", "generic_json", "Generic JSON"). Everything CORE forwards arrives through
    it, so it says nothing about which tool raised the alert."""
    words = (connector_type or "").replace("_", " ").replace("-", " ").lower().split()
    deduped = [w for i, w in enumerate(words) if i == 0 or w != words[i - 1]]
    return deduped == ["generic", "json"]


def alert_tool_name(connector_type: str | None, raw_event: object) -> str:
    """The tool an alert came from, as a readable name. An alert that came through the generic inbox is named by the sender's own ``source`` (kept at ``raw_event.source``); with no sender
    named it is "Generic JSON". Any other connector keeps its own name."""
    sender = raw_event.get("source") if isinstance(raw_event, dict) else None
    sender = sender.strip() if isinstance(sender, str) else ""
    if is_generic_inbox(connector_type) or not (connector_type or "").strip():
        return source_label(sender) if sender else ("Generic JSON" if (connector_type or "").strip() else "Unknown")
    return source_label(connector_type)


def narrative_names_the_inbox(narrative: str | None) -> bool:
    """Whether a stored narrative was written with the inbox's name where the tool's belongs (narratives written before the tool was looked up): one to write again."""
    return bool(narrative) and "`Generic Generic JSON`" in narrative  # type: ignore[operator]

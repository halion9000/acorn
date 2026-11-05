"""Why an alert was raised, in plain facts: which tool, which rule, how serious and how sure, who and what it names, and the reasons the correlation step gave.

Only what the alert itself stores is used (nothing is guessed). The raw event is never copied out: a tool's raw payload can hold secrets and personal data, so only its tool name is read.
"""

from __future__ import annotations

from typing import Any

from app.services.alert_suppression import source_of

MAX_LIST = 5
MAX_TEXT = 300


def _text(v: Any, limit: int = MAX_TEXT) -> str:
    return " ".join(str(v).split())[:limit]


def _names(values: Any) -> str | None:
    items = [_text(v, 120) for v in (values if isinstance(values, list) else []) if str(v).strip()]
    if not items:
        return None
    extra = f" and {len(items) - MAX_LIST} more" if len(items) > MAX_LIST else ""
    return ", ".join(items[:MAX_LIST]) + extra


def why_raised(alert: Any) -> list[dict[str, str]]:
    """The facts about why this alert exists, as ``{label, value}`` rows in reading order. A fact the alert does not have is left out, never filled in."""
    rows: list[dict[str, str]] = []

    def add(label: str, value: Any) -> None:
        if value is None or not str(value).strip():
            return
        rows.append({"label": label, "value": _text(value)})

    add("Raised by", source_of(getattr(alert, "raw_event", None), getattr(alert, "connector_type", None)))
    rule = getattr(alert, "rule_name", None)
    rule_id = getattr(alert, "rule_id", None)
    add("Rule", f"{rule} ({rule_id})" if rule and rule_id and rule != rule_id else rule or rule_id)
    add("Severity", getattr(alert, "severity", None))
    confidence = getattr(alert, "confidence", None)
    label = getattr(alert, "confidence_label", None)
    if confidence is not None:
        add("Confidence", f"{confidence}%" + (f" ({label})" if label else ""))
    for reason in (getattr(alert, "confidence_rationale", None) or [])[:MAX_LIST]:
        add(
            "Because",
            reason if isinstance(reason, str) else (reason.get("text") or reason.get("reason") or "") if isinstance(reason, dict) else "",
        )
    add("Names the people", _names(getattr(alert, "affected_users", None)))
    add("Names the devices", _names(getattr(alert, "affected_hosts", None)))
    add("Names the addresses", _names(getattr(alert, "affected_ips", None)))
    add("Attack tactics", _names(getattr(alert, "mitre_tactics", None)))
    add("Attack techniques", _names(getattr(alert, "mitre_techniques", None)))
    created = getattr(alert, "created_at", None)
    add("Raised at", created.isoformat() if hasattr(created, "isoformat") else created)
    return rows

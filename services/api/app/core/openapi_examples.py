"""Example request bodies for the compliance routes, added to the API's OpenAPI document (roadmap r7-ai-23).

The examples are kept here, by route, so they can be read in one place and checked in one test: ``tests/test_openapi_examples.py`` validates each against the route's real request model, so an
example that has drifted from the model (a renamed field, a changed choice) fails there instead of misleading a reader of the API docs. The values are made up (Acme, example.com).
"""

from __future__ import annotations

from typing import Any

EXAMPLES: dict[tuple[str, str], dict[str, Any]] = {
    ("POST", "/api/v1/compliance/evidence/collect"): {"framework": "SOC2"},
    ("PATCH", "/api/v1/compliance/report-schedules/{schedule_id}"): {"enabled": False},
    ("POST", "/api/v1/compliance/report-schedules"): {"name": "Monday digest", "report_kind": "compliance_actions", "emails": ["amy@acme.example"], "frequency": "weekly", "day": 0, "hour_utc": 7},
    ("POST", "/api/v1/compliance/audits/{audit_id}/auditors"): {"email": "pat@auditfirm.example"},
    ("POST", "/api/v1/compliance/audits/{audit_id}/auditors/invite"): {"account_name": "pat-audit", "name": "Pat Lee", "email": "pat@auditfirm.example"},
    ("POST", "/api/v1/compliance/audits/{audit_id}/files"): {"name": "access-review-q3.pdf", "content_base64": "JVBERi0xLjQK"},
    ("POST", "/api/v1/compliance/evidence"): {
        "framework": "SOC2",
        "control_id": "CC6.1",
        "control_title": "Logical access security",
        "evidence_kind": "attestation",
        "summary": "Quarterly access review for Microsoft 365 signed off by the owner on 2026-10-01.",
    },
    ("POST", "/api/v1/compliance/evidence/{evidence_id}/review"): {"decision": "accepted", "reviewer": "dana@acme.example"},
    ("POST", "/api/v1/compliance/vendors"): {
        "name": "Acme Backup Co",
        "website": "https://backup.example.com",
        "service": "Offsite backup",
        "category": "Infrastructure",
        "owner": "Dana Reyes",
        "risk_level": "medium",
        "data_access": "sensitive",
        "mfa": True,
        "review_interval_months": 12,
    },
    ("PATCH", "/api/v1/compliance/vendors/{vendor_id}"): {"risk_level": "high", "notes": "Breach notice received 2026-10-20; review brought forward."},
    ("POST", "/api/v1/compliance/vendors/{vendor_id}/reviews"): {"title": "2026 annual review", "kind": "one_time", "due_date": "2026-12-15", "reviewer": "Dana Reyes"},
    ("POST", "/api/v1/compliance/vendors/{vendor_id}/reviews/{review_id}/complete"): {"outcome": "no_concerns", "findings": "SOC 2 Type II report reviewed; no exceptions."},
    ("POST", "/api/v1/compliance/vendors/{vendor_id}/questionnaires"): {"expires_days": 30, "send": False},
    ("PUT", "/api/v1/compliance/trust-center/public"): {"enabled": True, "new_link": False},
    ("POST", "/api/v1/compliance/vendors/{vendor_id}/documents"): {"name": "SOC 2 Type II report 2026", "doc_type": "SOC 2", "url": "https://trust.backup.example.com/soc2.pdf"},
    ("POST", "/api/v1/compliance/detected-applications/{app_id}/link"): {"vendor_id": "6f9619ff-8b86-d011-b42d-00cf4fc964ff"},
    ("POST", "/api/v1/compliance/access-reviews"): {
        "name": "Q4 2026 Microsoft 365 access review",
        "system": "Microsoft 365",
        "reviewer": "Dana Reyes",
        "due_date": "2026-12-01",
    },
    ("PUT", "/api/v1/compliance/tests/schedule"): {"nightly": True},
    ("PUT", "/api/v1/compliance/tests/library"): {"disabled": ["backups"]},
    ("PUT", "/api/v1/compliance/notices"): {"emails": ["compliance@example.com"], "webhook_url": "https://hooks.example.com/compliance", "weekly": True},
    ("PUT", "/api/v1/compliance/access-reviews/schedules"): {"system": "Microsoft 365", "reviewer": "Dana Reyes", "every_days": 90, "enabled": True},
    ("PATCH", "/api/v1/compliance/access-reviews/{review_id}/entries/{entry_id}"): {"decision": "remove", "note": "Left the company in September."},
    ("POST", "/api/v1/compliance/access-reviews/{review_id}/decide-all"): {"decision": "keep", "only_unflagged": True},
    ("POST", "/api/v1/compliance/audits"): {
        "name": "SOC 2 Type II 2026",
        "framework": "SOC2",
        "auditor": "Birch Assurance LLP",
        "period_start": "2026-01-01",
        "period_end": "2026-12-31",
    },
    ("PATCH", "/api/v1/compliance/audits/{audit_id}"): {"status": "fieldwork"},
    ("POST", "/api/v1/compliance/audits/{audit_id}/requests"): {"title": "Provide the list of terminated employees for the period", "control_id": "CC6.2", "owner": "Dana Reyes", "due_date": "2026-11-30"},
    ("PATCH", "/api/v1/compliance/audits/{audit_id}/requests/{request_id}"): {"status": "provided", "note": "Export attached.", "link": "https://files.acme.example/terminations-2026.csv"},
    ("PUT", "/api/v1/compliance/trust-center"): {
        "enabled": True,
        "headline": "Security at Acme",
        "about": "We protect customer data with MFA, encryption and a yearly independent audit.",
        "contact_email": "security@acme.example",
        "frameworks": ["SOC2"],
    },
    ("PUT", "/api/v1/compliance/controls/{framework}/{control_id}/owner"): {"owner": "Dana Reyes"},
    ("PUT", "/api/v1/compliance/frameworks/enabled"): {"frameworks": ["SOC2", "HIPAA"]},
    ("POST", "/api/v1/compliance/questionnaires"): {
        "name": "Birch Dental security questionnaire",
        "customer": "Birch Dental",
        "due_date": "2026-12-10",
        "questions": "Do you encrypt data at rest?\nIs MFA required for all staff?",
        "format": "lines",
    },
    ("PATCH", "/api/v1/compliance/questionnaires/{questionnaire_id}/items/{item_id}"): {"answer": "Yes. All laptops use BitLocker and cloud storage uses AES-256.", "approved": True, "save_to_library": True},
    ("POST", "/api/v1/compliance/answer-library"): {"question": "Do you encrypt data at rest?", "answer": "Yes. AES-256 for storage, BitLocker on laptops.", "category": "Data protection"},
    ("PATCH", "/api/v1/compliance/answer-library/{answer_id}"): {"confirm": True},
}


def add_request_examples(schema: dict[str, Any]) -> dict[str, Any]:
    """Puts each example on its route's JSON request body in an OpenAPI document (changes ``schema``, and returns it). A route that is not in the document is skipped."""
    for (method, path), example in EXAMPLES.items():
        op = schema.get("paths", {}).get(path, {}).get(method.lower())
        content = ((op or {}).get("requestBody") or {}).get("content", {}).get("application/json")
        if content is not None:
            content["example"] = example
    return schema

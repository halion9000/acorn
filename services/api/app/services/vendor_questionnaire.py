"""The security questionnaire a vendor answers on a link (r7-af-06, Hal 2026-11-21).

The questions are fixed here (one place, so the form, the validation and the staff view agree). Everything in this module is pure: the questions, checking a submitted form, and the pages.
The routes are in endpoints/public_pages.py (the vendor) and endpoints/vendor_management.py (staff).
"""

from __future__ import annotations

from typing import Any

from app.services.policy_links import _doc, _e  # the same page shell and escaping as the policy page

PUBLIC_PATH = "/api/v1/public/vendor-questionnaire/"
DEFAULT_DAYS = 30
CHOICES = ("yes", "no", "na")
CHOICE_LABEL = {"yes": "Yes", "no": "No", "na": "Not applicable"}
MAX_DETAIL = 1000

QUESTIONS: tuple[tuple[str, str], ...] = (
    ("mfa", "Do you require multi-factor authentication for all staff accounts and for admin access to systems that hold our data?"),
    ("encrypt_transit", "Is our data encrypted in transit (TLS 1.2 or newer)?"),
    ("encrypt_rest", "Is our data encrypted at rest?"),
    ("certification", "Do you hold a current SOC 2 report, ISO 27001 certificate or similar? (Name it in the details.)"),
    ("pentest", "Is an independent penetration test done at least once a year, with findings fixed?"),
    ("vuln_mgmt", "Do you scan for vulnerabilities and patch critical issues within 30 days?"),
    ("access", "Is access to our data limited to the staff who need it, and reviewed at least yearly?"),
    ("training", "Do all staff have background checks where the law allows and security awareness training every year?"),
    ("incident", "Do you have a written incident response plan, and will you tell us about a breach that affects our data within 72 hours?"),
    ("subprocessors", "Do you use other companies (subprocessors) to handle our data? (List them in the details.)"),
    ("location", "Is our data stored only in the United States? (Say where in the details if not.)"),
    ("backup", "Are backups taken and restores tested, with a disaster recovery plan?"),
    ("deletion", "Will you delete or return our data within 30 days when the contract ends?"),
    ("breach_history", "Has your company had a security breach in the last three years? (Describe it in the details if yes.)"),
)
KEYS = tuple(k for k, _ in QUESTIONS)


def validate(fields: dict[str, str]) -> tuple[dict[str, Any] | None, str | None]:
    """Check a submitted form (pure). Returns ({name, email, answers}, None) or (None, why not). Every question needs Yes, No or Not applicable; details are optional and capped."""
    name = " ".join(fields.get("name", "").split())[:120]
    email = fields.get("email", "").strip().lower()[:254]
    if not name or "@" not in email or " " in email:
        return None, "Give your full name and your e-mail address."
    answers: list[dict[str, str]] = []
    for key, question in QUESTIONS:
        choice = fields.get(f"q_{key}", "")
        if choice not in CHOICES:
            return None, f"Answer every question: this one is missing: {question}"
        answers.append({"key": key, "question": question, "answer": choice, "details": " ".join(fields.get(f"d_{key}", "").split())[:MAX_DETAIL]})
    return {"name": name, "email": email, "answers": answers}, None


def render_form(org: str, vendor: str, expires_on: str) -> str:
    rows = []
    for key, question in QUESTIONS:
        radios = "".join(f'<label class="r"><input type="radio" name="q_{key}" value="{c}" required> {CHOICE_LABEL[c]}</label>' for c in CHOICES)
        rows.append(
            f'<fieldset><legend>{_e(question)}</legend>{radios}'
            f'<input type="text" name="d_{key}" maxlength="{MAX_DETAIL}" placeholder="Details (optional)" aria-label="Details: {_e(question)}"></fieldset>'
        )
    body = (
        f"<h1>Security questionnaire</h1><p class=\"note\">{_e(org)} asks {_e(vendor)} to answer these questions. This link can be used once, until {_e(expires_on)}.</p>"
        '<form method="post"><label>Your full name<input type="text" name="name" maxlength="120" required autocomplete="name"></label>'
        '<label>Your e-mail address<input type="text" name="email" maxlength="254" required autocomplete="email"></label>'
        + "".join(rows)
        + '<button type="submit">Send answers</button></form>'
        "<style>fieldset{border:1px solid #e5e7eb;border-radius:8px;margin:.8rem 0;padding:.6rem}legend{font-weight:600;padding:0 .3rem}.r{display:inline-block;margin-right:1rem}</style>"
    )
    return _doc(f"Security questionnaire for {vendor}", body)

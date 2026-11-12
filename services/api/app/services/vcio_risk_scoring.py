"""vCIO Risk Scoring: a client's Business Review scored by risk, from Live Oak's scoring workbook and tool.

The question library (``app/data/vcio_risk_library.json``, 330 questions in nine categories) and every rule here come from that workbook: nothing is invented.

* Weight. Each question has a severity (impact x likelihood, the risk model of NIST SP 800-30): Critical 10 points, High 6, Medium 3, Low 1.
* Credit. The good answer earns all the points, Partial half, the bad answer none. For a question where "Yes" is the risk (exposed RDP) the good answer is "No". Unknown earns none: a
  control nobody verified is not an assured control. A Tech Stack question is answered Preferred, Alternative or None; Alternative (a capable product that is not the standard one) earns
  full credit by default and is counted as a standardisation opportunity. N/A and unanswered questions are left out of both points earned and points possible.
* Roll-up. A section's or category's score is points earned over points possible. A category holding a Critical item that scored nothing is capped at 84% (red), so one major gap cannot
  hide behind many passes. The overall score is the category scores averaged by the category weights; a category with nothing answered drops out.
* Platform. A Microsoft 365 client is not asked the Google Workspace questions, and the other way round.
* Ratings. Green at 95% or more, amber from 85%, red below: the bands the vCIO Toolbox uses.
* NIST CSF 2.0. Every question is mapped to a CSF function, giving a second reading of the same answers.

Pure functions: no database, no clock.
"""

from __future__ import annotations

import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

LIBRARY_FILE = Path(__file__).resolve().parents[1] / "data" / "vcio_risk_library.json"

SEVERITIES = ("Critical", "High", "Medium", "Low")
CSF_ORDER = ("Govern", "Identify", "Protect", "Detect", "Respond", "Recover")
PLATFORMS = ("m365", "google", "both")
YESNO_ANSWERS = ("Yes", "No", "Partial", "Unknown", "N/A")
VENDOR_ANSWERS = ("Preferred", "Alternative", "None", "Unknown", "N/A")
TOP_GAPS = 25

DEFAULTS: dict[str, Any] = {
    "points": {"Critical": 10, "High": 6, "Medium": 3, "Low": 1},
    "partial": 0.5,
    "unknown": 0.0,
    "alternative": 1.0,
    "cap_on": True,
    "cap": 0.84,
    "green": 0.95,
    "amber": 0.85,
    "weights": {
        "Administrative": 8,
        "Network & Infrastructure": 12,
        "Servers": 8,
        "Workstations": 12,
        "Cybersecurity & Risk": 20,
        "Backup & Disaster Recovery": 20,
        "Microsoft 365": 20,
        "Google Workspace": 20,
        "Tech Stack": 15,
    },
}
CATEGORY_ORDER = tuple(DEFAULTS["weights"])


@lru_cache(maxsize=1)
def library() -> tuple[dict[str, Any], ...]:
    """The questions, in the workbook's order. Read once."""
    return tuple(json.loads(LIBRARY_FILE.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def questions_by_id() -> dict[str, dict[str, Any]]:
    return {q["id"]: q for q in library()}


def allowed_answers(question: dict[str, Any]) -> tuple[str, ...]:
    return VENDOR_ANSWERS if question["type"] == "vendor" else YESNO_ANSWERS


def _number(value: Any, low: float, high: float, fallback: float) -> float:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) and low <= value <= high else fallback


def merge_settings(given: dict[str, Any] | None) -> dict[str, Any]:
    """The defaults with whatever valid values were given laid over them. Anything out of range, of the wrong kind or not a setting is ignored, so a stored assessment can never break the maths."""
    out = deepcopy(DEFAULTS)
    g = given if isinstance(given, dict) else {}
    for sev in SEVERITIES:
        out["points"][sev] = _number(
            (g.get("points") or {}).get(sev) if isinstance(g.get("points"), dict) else None, 0, 100, out["points"][sev]
        )
    for cat in CATEGORY_ORDER:
        out["weights"][cat] = _number(
            (g.get("weights") or {}).get(cat) if isinstance(g.get("weights"), dict) else None, 0, 100, out["weights"][cat]
        )
    for key in ("partial", "unknown", "alternative", "cap", "green", "amber"):
        out[key] = _number(g.get(key), 0, 1, out[key])
    if isinstance(g.get("cap_on"), bool):
        out["cap_on"] = g["cap_on"]
    return out


def excluded(question: dict[str, Any], platform: str) -> bool:
    """A question the client's platform makes moot: the other suite's questions."""
    return (platform == "m365" and question["category"] == "Google Workspace") or (
        platform == "google" and question["category"] == "Microsoft 365"
    )


def severity_of(question: dict[str, Any], overrides: dict[str, str]) -> str:
    chosen = overrides.get(question["id"])
    return chosen if chosen in SEVERITIES else question["severity"]


def credit(question: dict[str, Any], answer: str | None, settings: dict[str, Any], platform: str) -> float | None:
    """The share of the question's points its answer earns; None when it does not count (no answer, N/A, or the other platform's question)."""
    if not answer or answer == "N/A" or excluded(question, platform):
        return None
    if question["type"] == "vendor":
        return (
            1.0
            if answer == "Preferred"
            else settings["alternative"]
            if answer == "Alternative"
            else settings["unknown"]
            if answer == "Unknown"
            else 0.0
        )
    if answer == "Partial":
        return settings["partial"]
    if answer == "Unknown":
        return settings["unknown"]
    return 1.0 if answer == question["good"] else 0.0


def rating(score: float | None, settings: dict[str, Any]) -> str:
    return "na" if score is None else "green" if score >= settings["green"] else "amber" if score >= settings["amber"] else "red"


def _aggregate(
    questions: list[dict[str, Any]], answers: dict[str, str], overrides: dict[str, str], settings: dict[str, Any], platform: str
) -> dict[str, Any]:
    possible = earned = 0.0
    critical = total = answered = 0
    for q in questions:
        if excluded(q, platform):
            continue
        total += 1
        c = credit(q, answers.get(q["id"]), settings, platform)
        if c is None:
            continue
        answered += 1
        sev = severity_of(q, overrides)
        weight = settings["points"][sev]
        possible += weight
        earned += weight * c
        if sev == "Critical" and c == 0:
            critical += 1
    raw = earned / possible if possible else None
    score = None if raw is None else min(raw, settings["cap"]) if settings["cap_on"] and critical > 0 else raw
    return {
        "questions": total,
        "answered": answered,
        "points_possible": round(possible, 4),
        "points_earned": round(earned, 4),
        "critical_gaps": critical,
        "raw": raw,
        "score": score,
        "rating": rating(score, settings),
    }


def scorecard(
    answers: dict[str, str],
    platform: str = "m365",
    severity_overrides: dict[str, str] | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Everything the Scorecard shows, from the answers (question id -> answer): the overall score, each category and its sections, the NIST CSF 2.0 reading, the gaps that lose the most
    points and the counts of what is still open or unknown."""
    s = merge_settings(settings)
    over = severity_overrides or {}
    qs = list(library())
    categories = []
    for name in CATEGORY_ORDER:
        mine = [q for q in qs if q["category"] == name]
        sections: list[str] = list(dict.fromkeys(q["subsection"] for q in mine))
        agg = _aggregate(mine, answers, over, s, platform)
        categories.append(
            {
                "name": name,
                "weight": s["weights"][name],
                "excluded": bool(mine) and all(excluded(q, platform) for q in mine),
                **agg,
                # A section shows its own points over points; the cap belongs to the category.
                "sections": [
                    {
                        "name": sec,
                        **{
                            k: v
                            for k, v in _aggregate([q for q in mine if q["subsection"] == sec], answers, over, s, platform).items()
                            if k != "score"
                        },
                    }
                    for sec in sections
                ],
            }
        )
    for c in categories:
        for sec in c["sections"]:
            sec["score"] = sec["raw"]
            sec["rating"] = rating(sec["raw"], s)
    weight_sum = sum(c["weight"] for c in categories if c["score"] is not None)
    overall = sum(c["score"] * c["weight"] for c in categories if c["score"] is not None) / weight_sum if weight_sum else None
    csf = [{"name": f, **_aggregate([q for q in qs if q["csf_function"] == f], answers, over, s, platform)} for f in CSF_ORDER]
    gaps = []
    for index, q in enumerate(qs):
        c = credit(q, answers.get(q["id"]), s, platform)
        if c is None:
            continue
        sev = severity_of(q, over)
        lost = s["points"][sev] * (1 - c)
        if lost > 0:
            gaps.append(
                (
                    -lost,
                    -(len(SEVERITIES) - SEVERITIES.index(sev)),
                    index,
                    {"id": q["id"], "severity": sev, "answer": answers[q["id"]], "points_lost": round(lost, 4)},
                )
            )
    visible = [q for q in qs if not excluded(q, platform)]
    given = {q["id"]: answers.get(q["id"]) for q in visible}
    return {
        "overall": overall,
        "rating": rating(overall, s),
        "categories": categories,
        "csf": csf,
        "gaps": [g[3] for g in sorted(gaps, key=lambda g: g[:3])][:TOP_GAPS],
        "gap_count": len(gaps),
        "total": len(visible),
        "answered": sum(1 for a in given.values() if a),
        "open": sum(1 for a in given.values() if not a),
        "unknown": sum(1 for a in given.values() if a == "Unknown"),
        "alternative_vendors": sum(1 for a in given.values() if a == "Alternative"),
        "settings": s,
    }

"""The status values a page may filter on, shared with the web app.

A filter that sends a value the server never stores shows an empty list and nothing says why (the Roles filter on the audit log did for months). The web keeps the
values in ``apps/web/src/lib/filterValues.json`` and tests its own filters against that file; this test keeps the file equal to what the server really matches.
"""

import json
from pathlib import Path

from app.api.v1.endpoints import alerts, cases
from app.services.alert_status import FINISHED_ALERT_STATUSES

SHARED = Path(__file__).resolve().parents[3] / "apps" / "web" / "src" / "lib" / "filterValues.json"


def shared() -> dict[str, list[str]]:
    return json.loads(SHARED.read_text(encoding="utf-8"))


def test_the_alert_statuses_the_web_may_filter_on_are_the_ones_the_server_matches():
    assert shared()["alert_status"] == list(alerts.FILTER_STATUSES)
    # Every status that counts as finished is one of them, so a "closed" tab can never be offered for a value the list cannot match.
    assert set(FINISHED_ALERT_STATUSES) <= set(alerts.FILTER_STATUSES)
    assert len(set(alerts.FILTER_STATUSES)) == len(alerts.FILTER_STATUSES)


def test_the_case_statuses_the_web_may_filter_on_are_the_ones_the_server_matches():
    assert shared()["case_status"] == list(cases.FILTER_STATUSES)
    # A case can only be moved to a status the filter can find again.
    for status, onward in cases._TRANSITIONS.items():
        assert {status, *onward} <= set(cases.FILTER_STATUSES)

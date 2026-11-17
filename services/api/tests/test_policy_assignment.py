"""Who must accept which policy and when they are reminded: the states, the reminder cadence, the one e-mail per person that lists everything they owe."""

import uuid
from datetime import UTC, date, datetime, timedelta

from app.services.policy_assignment import Owed, default_due, reminder_due, reminder_message, state_of
from app.workers.policy_reminder_worker import Row, groups_to_remind, message_for

TODAY = date(2026, 11, 17)
NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
T1, T2 = uuid.uuid4(), uuid.uuid4()


def row(email="a@x.com", title="AUP", due=TODAY + timedelta(days=5), last=None, accepted=False, tenant=T1, name=None):
    return Row(uuid.uuid4(), tenant, email, name, title, due, last, accepted)


def test_state_and_default_due():
    assert default_due(TODAY) == date(2026, 12, 1)
    assert state_of(TODAY, False, TODAY) == "pending", "due today is not overdue yet"
    assert state_of(TODAY - timedelta(days=1), False, TODAY) == "overdue"
    assert state_of(TODAY - timedelta(days=30), True, TODAY) == "accepted"


def test_a_reminder_is_due_at_once_then_weekly_and_every_three_days_once_overdue():
    future, past = TODAY + timedelta(days=9), TODAY - timedelta(days=2)
    assert reminder_due(None, future, NOW)
    assert not reminder_due(NOW - timedelta(days=3), future, NOW)
    assert reminder_due(NOW - timedelta(days=7), future, NOW)
    assert not reminder_due(NOW - timedelta(days=2), past, NOW)
    assert reminder_due(NOW - timedelta(days=3), past, NOW)
    assert reminder_due(NOW - timedelta(days=7) + timedelta(minutes=30), future, NOW), "an hourly pass does not slip a whole day"


def test_one_message_per_person_lists_everything_they_owe_and_nothing_they_accepted():
    rows = [
        row("a@x.com", "AUP"),
        row("a@x.com", "Backup", due=TODAY - timedelta(days=1)),
        row("a@x.com", "Done already", accepted=True),
        row("b@x.com", "AUP", last=NOW - timedelta(days=1)),  # told yesterday: not due again
        row("c@x.com", "AUP", accepted=True),
        row("a@x.com", "Other org", tenant=T2),
    ]
    due = groups_to_remind(rows, NOW)
    assert set(due) == {(T1, "a@x.com"), (T2, "a@x.com")}, "per organization, only the people who are due"
    titles = sorted(r.title for r in due[(T1, "a@x.com")])
    assert titles == ["AUP", "Backup"], "what is owed, not what was accepted"


def test_the_message_names_each_policy_its_day_and_whether_it_is_overdue_and_links_to_my_policies():
    subject, body = reminder_message("Ann", [Owed("Backup", TODAY - timedelta(days=1), True), Owed("AUP", TODAY + timedelta(days=5), False)], "https://acorn.example/my-policies")
    assert subject == "[A.C.O.R.N] Overdue: 2 policies to read and accept"
    assert "- Backup: due 2026-11-16 (overdue)" in body and "- AUP: due 2026-11-22" in body and "Hello Ann," in body
    assert "https://acorn.example/my-policies" in body
    one_subject, one_body = reminder_message(None, [Owed("AUP", TODAY, False)], "")
    assert one_subject == "[A.C.O.R.N] 1 policy to read and accept" and "Hello," in one_body and "go to My policies" in one_body
    assert message_for([row("a@x.com", "AUP", due=TODAY - timedelta(days=1), name="Ann")], TODAY, "")[0].startswith("[A.C.O.R.N] Overdue")


def test_accepting_needs_reports_read_which_cores_key_lacks_and_refuses_any_api_key():
    import asyncio
    from types import SimpleNamespace

    from app.api.v1.endpoints import me_policies as me
    from app.scripts.bootstrap_production import CORE_KEY_SCOPES
    from fastapi import HTTPException

    assert "reports:read" not in CORE_KEY_SCOPES and "reports:read" in __import__("app.core.security", fromlist=["ROLE_PERMISSIONS"]).ROLE_PERMISSIONS["viewer"]
    key_user = SimpleNamespace(tenant_id=uuid.uuid4(), user_id=uuid.uuid4(), email="core@x", scopes=["reports:read"])
    with __import__("pytest").raises(HTTPException) as e:
        asyncio.run(me.accept_policy(uuid.uuid4(), key_user, None))
    assert e.value.status_code == 403 and "API key" in e.value.detail

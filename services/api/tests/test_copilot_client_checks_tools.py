"""Leafy's read-only tools over the clients' tool checks and our own Secureframe report."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app import copilot_tools as ct
from app.api.v1.endpoints.secureframe import SecureframeBody
from app.services.copilot_textcalls import TEXT_CALLABLE, parse_text_tool_calls
from app.services.fleet_posture import FleetCheck

TID = str(uuid.uuid4())


def _check(client: str, source: str, key: str, status: str, evidence: str = "", **kw) -> FleetCheck:
    return FleetCheck(client_id=str(uuid.uuid4()), client_name=client, source=source, key=key, status=status, evidence=evidence, **kw)


class _Session:
    """A stand-in for the tenant session: ``async with`` gives itself back, ``execute`` answers with the prepared row."""

    def __init__(self, row=None):
        self.row = row

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def execute(self, *_a, **_k):
        result = MagicMock()
        result.scalar_one_or_none.return_value = self.row
        return result


def _fleet(checks):
    return AsyncMock(return_value=(checks, {}, {}))


CHECKS = [
    _check(
        "Acme",
        "threatmate-google",
        "threatmate_google_admins",
        "not_met",
        "2 super admins have no 2-Step",
        items=("a@acme.com", "b@acme.com"),
    ),
    _check("Acme", "cipp", "mfa_admins", "met", "all admins enrolled"),
    _check("Birch", "threatmate", "threatmate_deep_dark_web", "partly", "1 plaintext secret found"),
    _check("Birch", "threatmate-google", "threatmate_google_stale_accounts", "not_met", "4 accounts unused for 90 days", accepted=True),
]


@pytest.mark.asyncio
async def test_client_checks_lists_only_what_is_not_fine_worst_first_and_accepted_ones_after():
    with (
        patch.object(ct, "_get_session", AsyncMock(return_value=_Session())),
        patch("app.api.v1.endpoints.client_posture._fleet_checks", _fleet(CHECKS)),
    ):
        out = await ct.client_checks(tenant_id=TID)
    assert [r["check"] for r in out["checks"]] == [
        "threatmate_google_admins",
        "threatmate_deep_dark_web",
        "threatmate_google_stale_accounts",
    ]
    assert out["count"] == 3 and out["checks"][0]["items"] == ["a@acme.com", "b@acme.com"]
    assert out["checks"][2]["accepted_by_a_person"] is True


@pytest.mark.asyncio
async def test_client_checks_filters_by_client_source_and_a_word_and_can_include_fine_checks():
    with (
        patch.object(ct, "_get_session", AsyncMock(return_value=_Session())),
        patch("app.api.v1.endpoints.client_posture._fleet_checks", _fleet(CHECKS)),
    ):
        by_client = await ct.client_checks(tenant_id=TID, client="birch")
        by_source = await ct.client_checks(tenant_id=TID, source="threatmate-google")
        by_word = await ct.client_checks(tenant_id=TID, query="plaintext")
        everything = await ct.client_checks(tenant_id=TID, client="acme", include_met=True)
        nothing = await ct.client_checks(tenant_id=TID, client="zzz")
    assert {r["client"] for r in by_client["checks"]} == {"Birch"} and by_client["count"] == 2
    assert {r["source"] for r in by_source["checks"]} == {"threatmate-google"} and by_source["count"] == 2
    assert [r["check"] for r in by_word["checks"]] == ["threatmate_deep_dark_web"]
    assert everything["count"] == 2
    assert nothing["checks"] == [] and "note" in nothing


@pytest.mark.asyncio
async def test_client_checks_caps_the_rows_and_trims_long_evidence_and_item_lists():
    many = [_check(f"C{i:02d}", "threatmate", "k", "not_met", "x" * 900, items=tuple(f"i{n}" for n in range(30))) for i in range(60)]
    with (
        patch.object(ct, "_get_session", AsyncMock(return_value=_Session())),
        patch("app.api.v1.endpoints.client_posture._fleet_checks", _fleet(many)),
    ):
        out = await ct.client_checks(tenant_id=TID, limit=500)
    assert out["count"] == 60 and out["shown"] == 50
    row = out["checks"][0]
    assert len(row["evidence"]) == 300 and len(row["items"]) == 10 and row["more_items"] == 20


@pytest.mark.asyncio
async def test_a_bad_tenant_id_is_refused():
    assert (await ct.client_checks(tenant_id="nope")) == {"error": "invalid tenant_id"}
    assert (await ct.secureframe_status(tenant_id="nope")) == {"error": "invalid tenant_id"}


def _report() -> dict:
    return {
        "tests": {"total": 10, "enabled": 9, "passing": 6, "failing": 3, "not_evaluated": 0, "disabled": 1},
        "frameworks": [{"key": "NIST_CSF_2", "name": "NIST CSF 2.0", "failing": 2, "passing": 8}],
        "failing": [{"title": "MFA on admins", "owner": "Hal", "failing_since": "2026-10-01T00:00:00Z", "frameworks": ["NIST_CSF_2"]}],
        "risks": 6,
        "policies": 44,
        "requirements": [
            {"framework": "NIST_CSF_2", "key": "GV.OC-01", "title": "Context", "health": "healthy", "controls": []},
            {"framework": "NIST_CSF_2", "key": "GV.OC-02", "title": "Stakeholders", "health": "unhealthy", "controls": []},
            {"framework": "CIS_IG1", "key": "9.2", "title": "DNS filtering", "health": "not_tested", "controls": []},
        ],
    }


@pytest.mark.asyncio
async def test_secureframe_status_answers_not_connected_until_a_report_exists():
    with patch.object(ct, "_get_session", AsyncMock(return_value=_Session(None))):
        out = await ct.secureframe_status(tenant_id=TID)
    assert out["connected"] is False


@pytest.mark.asyncio
async def test_secureframe_status_gives_the_counts_and_the_unhealthy_requirements_of_one_framework():
    row = SimpleNamespace(
        report=SecureframeBody.model_validate(_report()).model_dump(mode="json"), received_at=datetime(2026, 10, 29, tzinfo=UTC)
    )
    with patch.object(ct, "_get_session", AsyncMock(return_value=_Session(row))):
        plain = await ct.secureframe_status(tenant_id=TID)
        nist = await ct.secureframe_status(tenant_id=TID, framework="NIST-CSF")
        cis = await ct.secureframe_status(tenant_id=TID, framework="cis_ig1")
    assert plain["risks"] == 6 and plain["policies"] == 44 and plain["passing_percent"] == pytest.approx(66.7)
    assert plain["oldest_failing_tests"][0]["owner"] == "Hal" and "framework" not in plain
    assert nist["requirements_by_health"] == {"healthy": 1, "unhealthy": 1}
    assert [r["id"] for r in nist["requirements_not_healthy"]] == ["GV.OC-02"]
    assert [r["id"] for r in cis["requirements_not_healthy"]] == ["9.2"]


def test_both_tools_are_registered_permissioned_and_callable_from_text():
    for name, perm in (("client_checks", "alerts:read"), ("secureframe_status", "reports:read")):
        assert ct.TOOL_PERMISSIONS[name] == perm
        assert name in ct._COPILOT_TOOL_DISPATCH
        assert any(t["function"]["name"] == name for t in ct.COPILOT_TOOL_SCHEMAS)
        assert name in TEXT_CALLABLE
    assert parse_text_tool_calls('```tool_use\nclient_checks\n{"client": "Acme"}\n```') == [("client_checks", {"client": "Acme"})]


ACME, BIRCH, BIRCHWOOD = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
NAMES = {ACME: "Acme Dental", BIRCH: "Birch Law", BIRCHWOOD: "Birchwood Farms"}


def _change(cid, key, now, was, hours_ago=1):
    return SimpleNamespace(
        client_id=cid,
        client_name=NAMES[cid],
        key=key,
        source="threatmate",
        status=now,
        previous_status=was,
        observed_at=datetime(2026, 10, 29, 12 - hours_ago, tzinfo=UTC),
    )


def _scope_patch():
    return patch("app.api.v1.endpoints.client_posture._scope", AsyncMock(return_value=([uuid.uuid4(), ACME, BIRCH, BIRCHWOOD], NAMES)))


@pytest.mark.asyncio
async def test_client_changes_lists_what_moved_for_one_client_or_all_and_refuses_an_unclear_name():
    rows = [_change(ACME, "threatmate_patching", "not_met", "met"), _change(BIRCH, "threatmate_dmarc", "met", "partly", 2)]
    fleet = AsyncMock(return_value=rows)
    with (
        patch.object(ct, "_get_session", AsyncMock(return_value=_Session())),
        _scope_patch(),
        patch("app.api.v1.endpoints.client_posture.fleet_changes", fleet),
    ):
        one = await ct.client_changes(tenant_id=TID, client="acme")
        everyone = await ct.client_changes(tenant_id=TID, days=3)
        several = await ct.client_changes(tenant_id=TID, client="birch")
        nobody = await ct.client_changes(tenant_id=TID, client="zzz")
    assert one["count"] == 1 and one["changes"][0] == {
        "client": "Acme Dental",
        "check": "threatmate_patching",
        "source": "threatmate",
        "now": "not_met",
        "was": "met",
        "when": "2026-10-29T11:00:00+00:00",
    }
    assert everyone["count"] == 2 and everyone["days"] == 3
    assert several["error"] == "several clients fit that name" and several["clients"] == ["Birch Law", "Birchwood Farms"]
    assert "no client is named like" in nobody["error"]


@pytest.mark.asyncio
async def test_client_changes_says_so_when_nothing_changed():
    with (
        patch.object(ct, "_get_session", AsyncMock(return_value=_Session())),
        _scope_patch(),
        patch("app.api.v1.endpoints.client_posture.fleet_changes", AsyncMock(return_value=[])),
    ):
        out = await ct.client_changes(tenant_id=TID)
    assert out["changes"] == [] and "note" in out


class _Posture:
    def model_dump(self, mode="json"):
        return {
            "devices": {"total": 20, "needs_attention": 3},
            "identity": {"people": 40, "without_mfa": 2},
            "alerts": {"open": 5, "critical": 1},
            "open_cases": 1,
            "tools": [{"vendor": "huntress"}, {"vendor": "ninjaone"}, {"vendor": "huntress"}],
            "tool_checks": {
                "threatmate": {
                    "checks": [
                        {"key": "a_met", "status": "met", "evidence": "fine"},
                        {"key": "b_partly", "status": "partly", "evidence": "so so"},
                        {"key": "c_bad", "status": "not_met", "evidence": "x" * 500},
                        {"key": "d_accepted", "status": "not_met", "evidence": "", "accepted": {"reason": "ok"}},
                    ]
                }
            },
        }


@pytest.mark.asyncio
async def test_client_overview_summarises_one_client_with_its_worst_checks_first():
    posture = AsyncMock(return_value=_Posture())
    with (
        patch.object(ct, "_get_session", AsyncMock(return_value=_Session())),
        _scope_patch(),
        patch("app.api.v1.endpoints.client_posture.client_posture", posture),
    ):
        out = await ct.client_overview(tenant_id=TID, client="Acme Dental")
        unclear = await ct.client_overview(tenant_id=TID, client="birch")
        missing = await ct.client_overview(tenant_id=TID, client="")
    assert out["client"] == "Acme Dental" and out["tools"] == ["huntress", "ninjaone"] and out["checks_not_fine"] == 2
    assert [c["check"] for c in out["worst_checks"]] == ["c_bad", "b_partly"] and len(out["worst_checks"][0]["evidence"]) == 200
    assert out["devices"]["needs_attention"] == 3 and out["open_cases"] == 1
    assert posture.await_args.args[0] == ACME
    assert unclear["error"] == "several clients fit that name" and missing == {"error": "client is required"}


def test_the_new_tools_are_registered_permissioned_and_callable_from_text():
    for name in ("client_changes", "client_overview"):
        assert ct.TOOL_PERMISSIONS[name] == "alerts:read" and name in ct._COPILOT_TOOL_DISPATCH and name in TEXT_CALLABLE
        assert any(t["function"]["name"] == name for t in ct.COPILOT_TOOL_SCHEMAS)

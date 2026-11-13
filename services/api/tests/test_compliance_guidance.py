"""Every SOC 2 control says what it means, what it takes to meet it and what to attach, and the page gets all three with the control."""

import pytest
from app.api.v1.endpoints import compliance as ep
from app.services.compliance_catalog import CATALOGS
from app.services.compliance_guidance import GUIDANCE, HIPAA, NIST_CSF, SOC2, guidance_for


def test_every_soc_2_control_of_the_catalog_has_guidance_and_no_guidance_is_for_a_control_that_does_not_exist():
    ids = [cid for _group, cid, _title in CATALOGS["SOC2"]]
    assert len(ids) == 61
    assert [cid for cid in ids if cid not in SOC2] == [], "a control with no guidance is a title and an empty box again"
    assert sorted(set(SOC2) - set(ids)) == [], "guidance for an id the catalog does not have is never shown"


def test_every_hipaa_and_nist_csf_control_of_the_catalog_has_guidance_and_none_is_for_a_control_that_does_not_exist():
    for key, written, expected in (("HIPAA", HIPAA, 63), ("NIST-CSF", NIST_CSF, 106)):
        ids = [cid for _group, cid, _title in CATALOGS[key]]
        assert len(ids) == expected, key
        assert [cid for cid in ids if cid not in written] == [], key
        assert sorted(set(written) - set(ids)) == [], key


@pytest.mark.parametrize("written", [SOC2, HIPAA, NIST_CSF], ids=["SOC2", "HIPAA", "NIST-CSF"])
def test_each_piece_of_guidance_says_something_usable(written):
    for cid, g in written.items():
        assert len(g.meaning) >= 40 and g.meaning.endswith("."), cid
        assert len(g.to_meet) >= 1 and len(g.evidence) >= 1, cid
        assert all(len(item) >= 12 for item in (*g.to_meet, *g.evidence)), cid
        assert len(set(g.to_meet)) == len(g.to_meet) and len(set(g.evidence)) == len(g.evidence), cid
    assert sum(len(g.to_meet) for g in written.values()) >= 2 * len(written), "at least two things to do per control on average"


def test_soc_2_has_about_three_things_to_do_per_control():
    assert sum(len(g.to_meet) for g in SOC2.values()) >= 170


def test_guidance_is_looked_up_by_framework_and_control_and_is_none_where_there_is_none():
    assert guidance_for("SOC2", "CC6.1").to_meet[1].startswith("Multi-factor sign-in")
    assert guidance_for("SOC2", "CC9.9") is None
    assert guidance_for("ISO27001", "A.5.1") is None and guidance_for("nope", "CC6.1") is None
    assert guidance_for("HIPAA", "164.308(a)(1)(ii)(A)") is not None and guidance_for("NIST-CSF", "GV.OC-01") is not None
    assert set(GUIDANCE) == {"SOC2", "HIPAA", "NIST-CSF"}


@pytest.mark.asyncio
async def test_the_controls_of_a_framework_come_with_their_guidance_and_a_framework_without_any_comes_without():
    soc2 = {c.control_id: c for c in (await ep.list_framework_controls("SOC2")).controls}
    assert len(soc2) == 61
    cc11 = soc2["CC1.1"]
    assert cc11.title == "Commitment to integrity and ethical values" and cc11.group == "CC1 Control environment"
    assert cc11.meaning == "The company says how its people are expected to behave, and acts when they do not."
    assert cc11.to_meet[0].startswith("A code of conduct") and cc11.evidence_examples[0] == "The code of conduct with its approval date"
    assert all(c.meaning and c.to_meet and c.evidence_examples for c in soc2.values())
    for key in ("HIPAA", "NIST-CSF"):
        written = (await ep.list_framework_controls(key)).controls
        assert written and all(c.meaning and c.to_meet and c.evidence_examples for c in written), key
    unwritten = [k for k in ep.FRAMEWORKS if k not in GUIDANCE]
    assert unwritten, "some framework still has no guidance, to show it comes without"
    plain = (await ep.list_framework_controls(unwritten[0])).controls
    assert plain and all(c.meaning is None and c.to_meet == [] and c.evidence_examples == [] for c in plain)


def test_the_controls_route_itself_answers_for_every_framework():
    """Asked for over HTTP, the way the page asks. The route's decorator once sat on a helper beside it: every framework answered 422 while the tests, which called the function directly, passed."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(ep.router, prefix="/api/v1")
    for route in ep.router.routes:
        for dep in getattr(route, "dependencies", []):
            app.dependency_overrides[dep.dependency] = lambda: None
    client = TestClient(app)
    for key in ep.FRAMEWORKS:
        answer = client.get(f"/api/v1/compliance/frameworks/{key}/controls")
        assert answer.status_code == 200, (key, answer.text[:200])
        body = answer.json()
        assert body["framework_id"] == key and len(body["controls"]) == len(ep.FRAMEWORKS[key]), key
    hipaa = client.get("/api/v1/compliance/frameworks/HIPAA/controls").json()["controls"]
    assert all(c["meaning"] and c["to_meet"] and c["evidence_examples"] for c in hipaa)
    assert client.get("/api/v1/compliance/frameworks/NOPE/controls").status_code == 404

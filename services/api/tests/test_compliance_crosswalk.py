"""The cross-framework crosswalk: every control it names exists in its framework's catalog, and the lookups and overlap count correctly."""

from app.services import compliance_crosswalk as cw
from app.services.compliance_catalog import CATALOGS


def test_every_control_named_exists_in_its_own_frameworks_catalog():
    known = {fw: {cid for _g, cid, _t in rows} for fw, rows in CATALOGS.items()}
    missing = [(t, fw, i) for t, (_n, by_fw) in cw.TOPICS.items() for fw, ids in by_fw.items() for i in ids if i not in known.get(fw, set())]
    assert missing == []
    assert set(cw.FRAMEWORK_NAMES) == set(CATALOGS), "a framework added to the catalog gets a name here"


def test_every_topic_is_in_at_least_two_frameworks_or_it_is_not_a_crosswalk():
    assert [t for t, (_n, m) in cw.TOPICS.items() if len([f for f, ids in m.items() if ids]) < 2] == []


def test_topics_for_and_related_follow_a_control_across_frameworks():
    assert cw.topics_for("PCI-DSS", "Req-8.4") == ["authentication"]
    rel = cw.related("PCI-DSS", "Req-8.4")
    assert "PCI-DSS" not in rel
    assert "A.8.5" in rel["ISO27001"] and "6.5" in rel["CIS-IG1"] and "164.312(d)" in rel["HIPAA"]
    assert cw.related("SOC2", "CC1.1") == {} and cw.topics_for("SOC2", "CC1.1") == []


def test_a_control_in_several_topics_gets_the_controls_of_all_of_them():
    assert set(cw.topics_for("PCI-DSS", "Req-8.2")) == {"access-granting", "access-removal", "unique-ids"}
    rel = cw.related("PCI-DSS", "Req-8.2")
    assert "6.2" in rel["CIS-IG1"] and "164.312(a)(2)(i)" in rel["HIPAA"] and "A.5.18" in rel["ISO27001"]


def test_a_control_in_the_frameworks_list_carries_where_else_it_counts():
    from app.api.v1.endpoints.compliance import _control_item

    item = _control_item("PCI-DSS", "Req-8.4", "MFA")
    assert "A.8.5" in item.also_in["ISO27001"] and "PCI-DSS" not in item.also_in
    assert _control_item("SOC2", "CC1.1", "x").also_in == {}

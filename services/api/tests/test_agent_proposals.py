"""The proposal log's rules: the evidence rule, the header tally, and that the routes are guarded the way the plan says."""

import pytest
from app.api.v1.endpoints import agent_proposals as ep
from app.services.agent_proposals import MAX_EVIDENCE, EvidenceError, clean_evidence, tally


def test_a_proposal_with_no_evidence_is_refused():
    for raw in (None, [], [{}], [{"label": "  "}], [{"url": ""}], "nonsense", [42, None]):
        with pytest.raises(EvidenceError):
            clean_evidence(raw)


def test_evidence_is_trimmed_strings_become_labels_and_a_url_alone_is_enough():
    got = clean_evidence(["  the alert  ", {"label": "Huntress incident", "url": " https://x/y "}, {"url": "https://only/link"}, {"label": ""}])
    assert got == [{"label": "the alert"}, {"label": "Huntress incident", "url": "https://x/y"}, {"label": "https://only/link", "url": "https://only/link"}]


def test_evidence_is_capped():
    assert len(clean_evidence([f"e{i}" for i in range(50)])) == MAX_EVIDENCE


def test_tally_counts_each_rung_and_outcome_and_the_shadow_ones_nobody_has_judged():
    rows = [
        {"rung": "shadow", "outcome": "none"},
        {"rung": "shadow", "outcome": "accepted"},
        {"rung": "ask", "outcome": "rejected"},
        {"rung": "act_tell", "outcome": "none"},
    ]
    t = tally(rows)
    assert t["total"] == 4 and t["by_rung"]["shadow"] == 2 and t["by_rung"]["suggest"] == 0
    assert t["by_outcome"] == {"none": 2, "accepted": 1, "edited": 0, "rejected": 1, "expired": 0}
    assert t["shadow_unreviewed"] == 1


def _deps(route_path, method):
    for r in ep.router.routes:
        if r.path == "/agent-proposals" + route_path and method in r.methods:
            return r
    raise AssertionError((route_path, method))


def _guards(route):
    names = []
    for d in route.dependant.dependencies:
        names.append(getattr(d.call, "__qualname__", str(d.call)))
        for sub in d.dependencies:
            names.append(getattr(sub.call, "__qualname__", str(sub.call)))
    return " ".join(names)


def test_an_agents_token_cannot_mark_its_own_proposal():
    """Recording an outcome needs a signed-in person's session; the other routes use the ordinary permissions."""
    assert "require_signed_in_session" in _guards(_deps("/{proposal_id}/outcome", "POST"))
    assert "require_signed_in_session" not in _guards(_deps("", "POST"))


def test_the_routes_do_not_expose_anything_that_approves_or_resolves():
    paths = {r.path for r in ep.router.routes}
    assert paths == {"/agent-proposals", "/agent-proposals/{proposal_id}/outcome"}


def test_the_tally_gives_each_agent_its_own_scorecard_busiest_first():
    rows = [
        {"agent": "cipher", "rung": "act_tell", "outcome": "none"},
        {"agent": "cipher", "rung": "shadow", "outcome": "accepted"},
        {"agent": "cipher", "rung": "ask", "outcome": "rejected"},
        {"agent": "jax", "rung": "suggest", "outcome": "expired"},
        {"agent": "cipher", "rung": "act_quiet", "outcome": "edited"},
    ]
    t = tally(rows)
    assert list(t["by_agent"]) == ["cipher", "jax"]
    assert t["by_agent"]["cipher"] == {"total": 4, "acted": 2, "shadow": 1, "asked": 1, "suggested": 0, "accepted": 1, "edited": 1, "rejected": 1, "expired": 0}
    assert t["by_agent"]["jax"]["suggested"] == 1 and t["by_agent"]["jax"]["expired"] == 1
    assert tally([{"rung": "ask", "outcome": "none"}])["by_agent"]["unknown"]["asked"] == 1

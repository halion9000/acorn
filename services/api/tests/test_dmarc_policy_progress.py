"""DMARC policy progress per client: how many domains reject, quarantine or only monitor, and which monitoring ones are ready to enforce."""

from datetime import UTC, datetime

from app.api.v1.endpoints import dmarc as ep


def row(client, domain, policy, total=500, pass_rate=99.0, name=None):
    return ep.DomainRow(
        client_id=client,
        client_name=name or client.title(),
        matched=True,
        domain=domain,
        reports=3,
        total=total,
        passed=int(total * (pass_rate or 0) / 100),
        failed=0,
        pass_rate=pass_rate,
        policy=policy,
        last_report=datetime(2026, 11, 4, tzinfo=UTC),
    )


def test_each_clients_domains_are_counted_by_how_far_they_have_come():
    out = ep.policy_progress(
        [row("acme", "a.com", "reject"), row("acme", "b.com", "quarantine"), row("acme", "c.com", "none"), row("birch", "d.com", "none")]
    )
    by = {p.client_id: p for p in out}
    assert (by["acme"].domains, by["acme"].rejecting, by["acme"].quarantining, by["acme"].monitoring) == (3, 1, 1, 1)
    assert (by["birch"].domains, by["birch"].rejecting, by["birch"].quarantining, by["birch"].monitoring) == (1, 0, 0, 1)


def test_a_monitoring_domain_is_ready_only_with_enough_mail_and_a_high_pass_rate():
    out = ep.policy_progress(
        [
            row("acme", "ready.com", "none", total=500, pass_rate=99.0),
            row("acme", "exactly.com", "none", total=100, pass_rate=98.0),
            row("acme", "few.com", "none", total=99, pass_rate=100.0),
            row("acme", "low.com", "none", total=500, pass_rate=97.9),
            row("acme", "unknown.com", "none", total=500, pass_rate=None),
            row("acme", "enforcing.com", "reject", total=500, pass_rate=100.0),
        ]
    )
    assert out[0].ready_to_enforce == 2, "ready, and exactly at the bar; not too few, not too low, not unknown, not already enforcing"


def test_an_unrecognised_or_empty_policy_counts_as_monitoring_and_case_does_not_matter():
    out = ep.policy_progress([row("acme", "a.com", "REJECT"), row("acme", "b.com", ""), row("acme", "c.com", "weird")])
    assert (out[0].rejecting, out[0].monitoring) == (1, 2)


def test_the_clients_furthest_behind_come_first_and_no_domains_give_no_lines():
    out = ep.policy_progress(
        [row("zed", "z.com", "reject"), row("acme", "a.com", "none"), row("birch", "b.com", "quarantine"), row("birch", "c.com", "none")]
    )
    assert [p.client_id for p in out] == ["acme", "birch", "zed"]
    assert ep.policy_progress([]) == []

"""What the platform keeps and for how long: the page's words must follow the settings, and never promise a deletion that nothing performs."""

from types import SimpleNamespace as NS

from app.services.data_retention import retention_lines


def settings(**over):
    base = dict(
        RETENTION_SWEEPER_ENABLED=True,
        RETENTION_DRY_RUN=False,
        RETENTION_ALERTS_DAYS=0,
        ALERT_STALE_DAYS=30,
        RETENTION_POSTURE_HISTORY_DAYS=0,
        RETENTION_COPILOT_CONVERSATIONS_DAYS=90,
        RETENTION_DETECTION_SUGGESTIONS_DAYS=180,
        RETENTION_RESPONSE_ACTIONS_DEFAULT_DAYS=730,
        ALERT_EMAIL_LOG_RETENTION_DAYS=90,
    )
    base.update(over)
    return NS(**base)


def by(lines, what):
    return next(line for line in lines if line["what"] == what)


def test_every_line_says_what_how_long_and_what_ends_it():
    for line in retention_lines(settings()):
        assert all(line[k].strip() for k in ("what", "kept", "ends")), line


def test_alerts_are_kept_until_deleted_by_hand_unless_a_limit_is_set_and_then_the_number_is_the_setting():
    assert by(retention_lines(settings()), "Alerts")["kept"] == "Kept until deleted by hand"
    set_ = by(retention_lines(settings(RETENTION_ALERTS_DAYS=400)), "Alerts")
    assert "400 days" in set_["kept"] and "never deleted" in set_["ends"]


def test_stale_alerts_are_said_to_be_set_aside_never_deleted_and_the_number_follows_the_setting():
    on = by(retention_lines(settings(ALERT_STALE_DAYS=45)), "Stale alerts")
    assert "never deleted" in on["kept"] and "45 days" in on["ends"]
    off = by(retention_lines(settings(ALERT_STALE_DAYS=0)), "Stale alerts")
    assert "Not set aside" in off["kept"]


def test_when_the_cleaner_is_off_or_only_counting_nothing_that_it_would_delete_is_promised():
    for over, words in ((dict(RETENTION_SWEEPER_ENABLED=False), "switched off"), (dict(RETENTION_DRY_RUN=True), "count-only")):
        lines = retention_lines(settings(RETENTION_ALERTS_DAYS=400, RETENTION_POSTURE_HISTORY_DAYS=200, **over))
        for what in ("Alerts", "Copilot conversations", "Detection suggestions", "Finished response actions", "Check and count history (security checks, licence counts, scores)"):
            assert words in by(lines, what)["ends"], (what, over)


def test_things_nothing_deletes_say_so():
    lines = retention_lines(settings())
    for what in ("Cases and investigations", "Audit trail"):
        assert "deleted by hand" in by(lines, what)["kept"]
    assert by(lines, "Check and count history (security checks, licence counts, scores)")["kept"] == "Kept for ever"


def test_the_route_needs_alerts_read():
    from app.main import app
    from route_introspect import required_permissions, walk_routes

    found = {(m, p.replace("/api/v1", "", 1)): r for p, r in walk_routes(app.routes) for m in r.methods}
    assert set(required_permissions(found[("GET", "/data-retention")])) == {"alerts:read"}

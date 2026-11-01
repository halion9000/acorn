"""The plain-language warnings on Platform health."""

from app.api.v1.endpoints.health import pending_migrations, platform_warnings


def _w(**over):
    base = {"down": [], "disk": None, "pending": None, "core_feed": None, "device_feeds": [], "signins": None}
    base.update(over)
    return platform_warnings(**base)


def test_a_healthy_platform_has_no_warnings():
    assert (
        _w(
            disk={"used_percent": 40.0, "free_gb": 100},
            pending=[],
            core_feed={"silent": False},
            signins={"unscored": 0, "scored_last_24h": 5},
        )
        == []
    )


def test_each_problem_is_reported_and_errors_come_first():
    out = _w(
        down=["fusion"],
        disk={"used_percent": 91.0, "free_gb": 3.2},
        pending=["094_x.sql"],
        core_feed={"silent": True},
        device_feeds=[{"vendor": "addigy", "stalled": True}, {"vendor": "ninjaone", "stalled": False}],
        signins={"unscored": 10, "scored_last_24h": 0},
    )
    levels = [w["level"] for w in out]
    assert levels == sorted(levels, key=lambda lv: lv != "error")
    text = " | ".join(w["text"] for w in out)
    for needle in ("fusion", "094_x.sql", "CORE has not reported", "91.0%", "addigy", "none are scored"):
        assert needle in text, needle
    assert "ninjaone" not in text


def test_disk_below_the_threshold_and_scored_sign_ins_do_not_warn():
    assert _w(disk={"used_percent": 84.9, "free_gb": 9}, signins={"unscored": 4, "scored_last_24h": 7}) == []


class _BadDb:
    async def execute(self, *_a, **_k):
        raise RuntimeError("no table")


async def test_unreadable_migration_state_is_unknown_not_an_error():
    assert await pending_migrations(_BadDb()) is None


def test_a_large_scoring_backlog_is_reported_but_a_small_one_is_not():
    out = _w(signins={"unscored": 21294, "scored_last_24h": 602})
    assert [w["key"] for w in out] == ["backlog"]
    assert "21,294" in out[0]["text"]
    assert _w(signins={"unscored": 999, "scored_last_24h": 602}) == []


def test_nothing_scored_at_all_is_the_louder_message_and_not_reported_twice():
    out = _w(signins={"unscored": 5000, "scored_last_24h": 0})
    assert [w["key"] for w in out] == ["signins"]


def test_a_loop_that_stalled_is_a_warning_and_a_quiet_one_is_not():
    assert _w(loop={"window_seconds": 300, "samples": 290, "max_seconds": 0.2, "slow": False}) == []
    out = _w(loop={"window_seconds": 300, "samples": 290, "max_seconds": 4.1, "slow": True})
    assert [w["key"] for w in out] == ["loop"] and "4.1 s" in out[0]["text"] and "5 minutes" in out[0]["text"]


def test_the_microsoft_secret_row_counts_days_and_ignores_missing_or_bad_dates():
    from datetime import date

    from app.api.v1.endpoints.health import secret_expiry_row

    assert secret_expiry_row("2026-12-01", date(2026, 11, 1)) == {"expires_on": "2026-12-01", "days_left": 30}
    assert secret_expiry_row(" 2026-11-01 ", date(2026, 11, 1))["days_left"] == 0
    assert secret_expiry_row("2026-10-30", date(2026, 11, 1))["days_left"] == -2
    assert secret_expiry_row("", date(2026, 11, 1)) is None
    assert secret_expiry_row("next spring", date(2026, 11, 1)) is None


def test_the_secret_warns_from_thirty_days_and_is_an_error_from_seven():
    assert _w(secret={"expires_on": "2027-01-01", "days_left": 31}) == []
    month = _w(secret={"expires_on": "2026-12-01", "days_left": 30})
    assert [(w["key"], w["level"]) for w in month] == [("microsoft_secret", "warn")]
    assert "expires in 30 days" in month[0]["text"]
    week = _w(secret={"expires_on": "2026-11-08", "days_left": 7})
    assert week[0]["level"] == "error"
    assert "expires in 1 day " in _w(secret={"expires_on": "x", "days_left": 1})[0]["text"] + " "
    assert "expires today" in _w(secret={"expires_on": "x", "days_left": 0})[0]["text"]
    assert "has expired" in _w(secret={"expires_on": "x", "days_left": -3})[0]["text"]
    assert _w(secret=None) == []


def test_old_credentials_lists_the_feed_token_and_api_keys_past_their_limits_oldest_first():
    from datetime import UTC, datetime, timedelta

    from app.api.v1.endpoints.health import old_credentials

    now = datetime(2026, 11, 1, tzinfo=UTC)
    ago = lambda days: now - timedelta(days=days)  # noqa: E731
    out = old_credentials(ago(200), [("ci", ago(400)), ("new", ago(30)), ("edge", ago(365)), ("none", None)], now)
    assert [(c["kind"], c["age_days"]) for c in out] == [("API key ci", 400), ("API key edge", 365), ("CORE feed token", 200)]
    assert old_credentials(ago(179), [("k", ago(364))], now) == []
    assert old_credentials(None, [], now) == []


def test_an_old_credential_is_a_warning_that_names_it_and_never_a_value():
    out = _w(old_creds=[{"kind": "CORE feed token", "age_days": 200, "limit_days": 180}])
    assert [(w["key"], w["level"]) for w in out] == [("old_credentials", "warn")]
    assert "CORE feed token (200 days)" in out[0]["text"] and "put into CORE" in out[0]["text"]
    assert _w(old_creds=[]) == [] and _w(old_creds=None) == []
    many = _w(old_creds=[{"kind": f"API key {i}", "age_days": 400 - i, "limit_days": 365} for i in range(6)])
    assert "and 2 more" in many[0]["text"]


def test_the_database_query_finds_the_active_feed_token_and_keys_of_the_callers_tenant(tmp_path):
    import asyncio
    import uuid
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from app.api.v1.endpoints.health import _old_credentials_or_none
    from app.db.database import Base
    from app.models.inbox import TenantInboxToken
    from app.models.tenant import ApiKey, Tenant
    from sqlalchemy import create_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool

    path = tmp_path / "creds.db"
    sync = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(sync, tables=[Tenant.__table__, ApiKey.__table__, TenantInboxToken.__table__])
    mine, other = (
        Tenant(id=uuid.uuid4(), name="A", slug="a-" + uuid.uuid4().hex[:6]),
        Tenant(id=uuid.uuid4(), name="B", slug="b-" + uuid.uuid4().hex[:6]),
    )
    now = datetime.now(UTC)
    old = now - timedelta(days=400)
    with Session(sync, expire_on_commit=False) as s:
        s.add_all([mine, other])
        s.flush()
        s.add_all(
            [
                TenantInboxToken(
                    token="t-old-feed",
                    tenant_id=mine.id,
                    template_id="generic-json",
                    label="core-feed",
                    created_at=now - timedelta(days=200),
                ),
                TenantInboxToken(
                    token="t-revoked", tenant_id=mine.id, template_id="generic-json", label="core-feed", created_at=old, revoked_at=now
                ),
                TenantInboxToken(token="t-other", tenant_id=other.id, template_id="generic-json", label="core-feed", created_at=old),
                ApiKey(
                    id=uuid.uuid4(),
                    tenant_id=mine.id,
                    user_id=uuid.uuid4(),
                    name="ci",
                    key_prefix="aisoc_aaaaaa",
                    hashed_key="h1",
                    scopes=["*"],
                    is_active=True,
                    created_at=old,
                ),
                ApiKey(
                    id=uuid.uuid4(),
                    tenant_id=mine.id,
                    user_id=uuid.uuid4(),
                    name="dead",
                    key_prefix="aisoc_bbbbbb",
                    hashed_key="h2",
                    scopes=["*"],
                    is_active=False,
                    created_at=old,
                ),
                ApiKey(
                    id=uuid.uuid4(),
                    tenant_id=other.id,
                    user_id=uuid.uuid4(),
                    name="theirs",
                    key_prefix="aisoc_cccccc",
                    hashed_key="h3",
                    scopes=["*"],
                    is_active=True,
                    created_at=old,
                ),
            ]
        )
        s.commit()
    factory = async_sessionmaker(create_async_engine(f"sqlite+aiosqlite:///{path}", poolclass=NullPool), expire_on_commit=False)

    async def run():
        async with factory() as db:
            return await _old_credentials_or_none(db, SimpleNamespace(tenant_id=mine.id))

    found = asyncio.run(run())
    sync.dispose()
    assert found is not None, "the query must work, not be swallowed"
    assert [c["kind"] for c in found] == ["API key ci", "CORE feed token"]

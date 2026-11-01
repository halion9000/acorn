"""Sign in with Microsoft: every check that stands between "someone at Microsoft" and "someone in this console".

A fake Microsoft (a throwaway signing key, a token endpoint and a store for the short-lived state) lets each refusal be proved: a forged or foreign token, the wrong Microsoft tenant, a replayed state, a person outside the allowed group,
a disabled account, an identity that belongs to another account, and a stranger who must never become an administrator.
"""

import asyncio
import base64
import json
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import jwt as pyjwt
import pytest
from app.api.v1.endpoints import sso_microsoft as sso
from app.core.security import ROLE_PERMISSIONS, decode_token, verify_password
from app.db.database import Base
from app.models.tenant import Tenant, User
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

TID = "11111111-2222-3333-4444-555555555555"
CLIENT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
GROUP = "99999999-8888-7777-6666-555555555555"
OID = "0f0f0f0f-1111-2222-3333-444444444444"
REDIRECT = "https://acorn.example.com/api/v1/auth/sso/microsoft/callback"
HOME = uuid.uuid4()

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(key, kid):
    jwk = json.loads(pyjwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return jwk


JWKS = {"keys": [_jwk(KEY, "good-key")]}


def id_token(*, key=KEY, kid="good-key", alg="RS256", **over):
    now = int(time.time())
    claims = {
        "iss": f"https://login.microsoftonline.com/{TID}/v2.0",
        "aud": CLIENT,
        "exp": now + 600,
        "iat": now,
        "nbf": now,
        "sub": "pairwise-sub",
        "oid": OID,
        "tid": TID,
        "nonce": "NONCE",
        "name": "Jane Doe",
        "preferred_username": "Jane.Doe@LiveOak.example",
        "email": "someone.else@evil.example",
        **over,
    }
    claims = {k: v for k, v in claims.items() if v is not None}
    return pyjwt.encode(claims, key, algorithm=alg, headers={"kid": kid})


class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.down = False

    async def set(self, key, value, ex=None):
        if self.down:
            raise OSError("redis down")
        self.data[key] = value
        self.ttls[key] = ex

    async def getdel(self, key):
        if self.down:
            raise OSError("redis down")
        return self.data.pop(key, None)


@pytest.fixture
def world(monkeypatch):
    for k, v in {
        "MS_SSO_TENANT_ID": TID,
        "MS_SSO_CLIENT_ID": CLIENT,
        "MS_SSO_CLIENT_SECRET": "s3cret-value",
        "MS_SSO_REDIRECT_URI": REDIRECT,
        "MS_SSO_ACORN_TENANT_ID": str(HOME),
    }.items():
        monkeypatch.setenv(k, v)
    for k in ("MS_SSO_GROUP_ID", "MS_SSO_NEW_USER_ROLE", "MS_SSO_PASSWORD_LOGIN", "MS_SSO_WEB_URL"):
        monkeypatch.delenv(k, raising=False)
    redis = FakeRedis()
    monkeypatch.setattr(sso, "_redis", redis)
    sso._keys_cache.clear()
    fetched = []

    async def get_json(url):
        fetched.append(url)
        if url.endswith("openid-configuration"):
            return {"jwks_uri": "https://login.microsoftonline.com/keys"}
        return JWKS

    monkeypatch.setattr(sso, "_get_json", get_json)
    token_endpoint = SimpleNamespace(status=200, body={"id_token": None}, calls=[])

    async def post_form(url, data):
        token_endpoint.calls.append((url, data))
        return token_endpoint.status, token_endpoint.body

    monkeypatch.setattr(sso, "_post_form", post_form)
    audit = AsyncMock()
    monkeypatch.setattr(sso, "emit_audit", audit)
    return SimpleNamespace(redis=redis, fetched=fetched, token=token_endpoint, audit=audit, monkeypatch=monkeypatch)


def run(fn):
    async def main():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as c:
            await c.run_sync(lambda conn: Base.metadata.create_all(conn, tables=[Tenant.__table__, User.__table__]))
        async with async_sessionmaker(engine, expire_on_commit=False)() as s:
            s.add(Tenant(id=HOME, name="Live Oak", slug="live-oak"))
            await s.commit()
            try:
                return await fn(s)
            finally:
                await engine.dispose()

    return asyncio.run(main())


def query(response):
    return {k: v[0] for k, v in parse_qs(urlsplit(response.headers["location"]).query).items()}


async def begin(world, next_="/alerts?x=1"):
    """Start a sign-in and return (state, nonce) as kept on the server."""
    response = await sso.microsoft_login(next=next_)
    state = query(response)["state"]
    return state, json.loads(world.redis.data[f"aisoc:sso:state:{state}"])


def user(db_tenant=HOME, **over):
    base = dict(tenant_id=db_tenant, email="jane.doe@liveoak.example", account_name="jane.doe", username="Jane", hashed_password="x", role="soc_analyst", is_active=True)
    return User(**{**base, **over})


# ─── Off by default ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_it_is_off_until_all_four_settings_are_there(monkeypatch):
    for k in ("MS_SSO_TENANT_ID", "MS_SSO_CLIENT_ID", "MS_SSO_CLIENT_SECRET", "MS_SSO_REDIRECT_URI"):
        monkeypatch.delenv(k, raising=False)
    assert sso.load_config() is None
    assert asyncio.run(sso.sso_status()).model_dump() == {"microsoft": False, "password_login": "all"}
    with pytest.raises(HTTPException) as e:
        asyncio.run(sso.microsoft_login(next=None))
    assert e.value.status_code == 501
    assert sso.password_login_allowed("viewer") is True
    monkeypatch.setenv("MS_SSO_TENANT_ID", TID)
    assert sso.load_config() is None, "three of four is still off"


def test_settings_are_read_safely(world):
    cfg = sso.load_config()
    assert cfg.new_user_role == "viewer" and cfg.password_login == "admins" and cfg.web_url == "https://acorn.example.com" and cfg.home_tenant == HOME
    for bad in ("tenant_admin", "platform_admin", "admin", "api_service", "no-such-role", ""):
        world.monkeypatch.setenv("MS_SSO_NEW_USER_ROLE", bad)
        assert sso.load_config().new_user_role == "viewer", bad
    world.monkeypatch.setenv("MS_SSO_NEW_USER_ROLE", "soc_analyst")
    assert sso.load_config().new_user_role == "soc_analyst"
    world.monkeypatch.setenv("MS_SSO_ACORN_TENANT_ID", "not-a-uuid")
    assert sso.load_config().home_tenant is None
    world.monkeypatch.setenv("MS_SSO_WEB_URL", "https://web.example.com/")
    assert sso.load_config().web_url == "https://web.example.com"
    assert {"viewer", "soc_analyst"} <= set(ROLE_PERMISSIONS)


def test_the_status_says_what_the_login_page_should_offer(world):
    assert asyncio.run(sso.sso_status()).model_dump() == {"microsoft": True, "password_login": "admins"}
    world.monkeypatch.setenv("MS_SSO_PASSWORD_LOGIN", "all")
    assert asyncio.run(sso.sso_status()).password_login == "all"


def test_with_sso_on_only_administrators_may_use_a_password_unless_the_setting_says_everyone(world):
    for role in ("platform_admin", "admin", "tenant_admin"):
        assert sso.password_login_allowed(role) is True
    for role in ("soc_lead", "soc_analyst", "threat_hunter", "viewer", "api_service"):
        assert sso.password_login_allowed(role) is False, role
    world.monkeypatch.setenv("MS_SSO_PASSWORD_LOGIN", "all")
    assert sso.password_login_allowed("viewer") is True


# ─── Starting ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_browser_is_sent_to_this_tenants_microsoft_with_state_nonce_and_pkce_and_they_are_kept_for_ten_minutes(world):
    async def go():
        response = await sso.microsoft_login(next="/cases/1")
        assert response.status_code == 302
        parts = urlsplit(response.headers["location"])
        assert f"{parts.scheme}://{parts.netloc}{parts.path}" == f"https://login.microsoftonline.com/{TID}/oauth2/v2.0/authorize"
        q = query(response)
        assert q["client_id"] == CLIENT and q["redirect_uri"] == REDIRECT and q["response_type"] == "code" and q["code_challenge_method"] == "S256"
        assert "openid" in q["scope"].split()
        saved = json.loads(world.redis.data[f"aisoc:sso:state:{q['state']}"])
        assert saved["next"] == "/cases/1" and len(saved["nonce"]) >= 32 and q["nonce"] == saved["nonce"]
        digest = base64.urlsafe_b64encode(__import__("hashlib").sha256(saved["verifier"].encode()).digest()).rstrip(b"=").decode()
        assert q["code_challenge"] == digest, "the challenge is the hash of the verifier kept on the server"
        assert world.redis.ttls[f"aisoc:sso:state:{q['state']}"] == 600
        assert "client_secret" not in response.headers["location"] and "s3cret-value" not in response.headers["location"]

    asyncio.run(go())


@pytest.mark.parametrize(
    ("given", "kept"),
    [
        ("/alerts?x=1", "/alerts?x=1"),
        ("https://evil.example/", "/"),
        ("//evil.example/x", "/"),
        ("/\\evil.example", "/"),
        ("javascript:alert(1)", "/"),
        ("/ok\r\nSet-Cookie: a=b", "/"),
        (None, "/"),
        ("", "/"),
    ],
)
def test_only_a_path_on_this_site_is_ever_gone_back_to(given, kept):
    assert sso.safe_next(given) == kept


def test_each_start_gets_its_own_state(world):
    async def go():
        a, _ = await begin(world)
        b, _ = await begin(world)
        assert a != b and len(world.redis.data) == 2

    asyncio.run(go())


def test_if_the_short_lived_store_is_down_the_start_says_so(world):
    world.redis.down = True
    with pytest.raises(HTTPException) as e:
        asyncio.run(sso.microsoft_login(next=None))
    assert e.value.status_code == 503


# ─── The ID token ────────────────────────────────────────────────────────────────────────────────────────────────────────

def verify(token, nonce="NONCE"):
    return asyncio.run(sso.verify_id_token(sso.load_config(), token, nonce))


def refused(token, code, nonce="NONCE"):
    with pytest.raises(sso.SsoFailure) as e:
        verify(token, nonce)
    assert e.value.code == code
    return e.value


def test_a_genuine_token_for_this_app_and_tenant_is_accepted(world):
    claims = verify(id_token())
    assert claims["oid"] == OID and claims["tid"] == TID


def test_a_token_signed_by_someone_else_is_refused_even_if_it_claims_the_right_key_id(world):
    refused(id_token(key=OTHER_KEY), "token")


def test_a_token_for_another_app_issuer_or_tenant_or_that_has_expired_is_refused(world):
    refused(id_token(aud="some-other-app"), "token")
    refused(id_token(iss="https://login.microsoftonline.com/other-tenant/v2.0"), "token")
    refused(id_token(tid="99999999-0000-0000-0000-000000000000"), "tenant")
    refused(id_token(exp=int(time.time()) - 3600, iat=int(time.time()) - 7200), "token")


def test_a_token_from_a_different_sign_in_is_refused_by_the_nonce(world):
    refused(id_token(nonce="SOMEONE-ELSES"), "token")
    refused(id_token(nonce=None), "token")


def test_a_token_with_no_permanent_id_is_refused(world):
    refused(id_token(oid=None), "token")


def test_unsigned_and_symmetric_tokens_are_refused(world):
    unsigned = pyjwt.encode({"iss": f"https://login.microsoftonline.com/{TID}/v2.0", "aud": CLIENT, "exp": int(time.time()) + 600, "iat": int(time.time()), "sub": "x", "oid": OID, "tid": TID, "nonce": "NONCE"}, key=None, algorithm="none")
    refused(unsigned, "token")
    hs = pyjwt.encode({"aud": CLIENT, "exp": int(time.time()) + 600}, "secret", algorithm="HS256", headers={"kid": "good-key"})
    refused(hs, "token")
    refused("not.a.jwt", "token")


def test_an_unknown_key_id_makes_one_fresh_look_at_microsofts_keys_and_then_refuses(world):
    refused(id_token(kid="mystery"), "token")
    key_fetches = [u for u in world.fetched if not u.endswith("openid-configuration")]
    assert len(key_fetches) == 2, "the keys were fetched once, then once more for the unknown id"


def test_the_keys_are_kept_so_a_second_sign_in_does_not_fetch_them_again(world):
    verify(id_token())
    first = len(world.fetched)
    verify(id_token())
    assert len(world.fetched) == first


# ─── The group ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_with_no_group_set_anyone_in_the_tenant_passes_the_group_check(world):
    sso.check_group(sso.load_config(), {})


def test_with_a_group_set_only_its_members_pass_and_a_missing_claim_is_a_refusal_not_a_pass(world):
    world.monkeypatch.setenv("MS_SSO_GROUP_ID", GROUP)
    cfg = sso.load_config()
    sso.check_group(cfg, {"groups": [GROUP]})
    sso.check_group(cfg, {"groups": ["other", GROUP.upper()]})
    for claims in ({"groups": ["other"]}, {"groups": []}, {}, {"_claim_names": {"groups": "src1"}}):
        with pytest.raises(sso.SsoFailure) as e:
            sso.check_group(cfg, claims)
        assert e.value.code == "group"


# ─── People ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

CLAIMS = {"tid": TID, "oid": OID, "preferred_username": "Jane.Doe@LiveOak.example", "name": "Jane Doe", "email": "evil@evil.example"}


def test_a_stranger_is_created_as_a_viewer_in_the_home_tenant_with_a_password_nobody_knows(world):
    async def go(db):
        person, outcome = await sso.resolve_user(db, sso.load_config(), CLAIMS)
        await db.commit()
        assert outcome == "created"
        assert (person.role, person.tenant_id, person.email) == ("viewer", HOME, "jane.doe@liveoak.example"), "the email comes from the user name, never the email claim"
        assert person.external_identity == f"entra:{TID}:{OID}" and person.username == "Jane Doe" and person.is_active
        assert not verify_password("", person.hashed_password) and not verify_password("password", person.hashed_password)

    run(go)


def test_a_stranger_never_becomes_an_administrator_whatever_the_setting(world):
    world.monkeypatch.setenv("MS_SSO_NEW_USER_ROLE", "platform_admin")

    async def go(db):
        person, _ = await sso.resolve_user(db, sso.load_config(), CLAIMS)
        assert person.role == "viewer"

    run(go)


def test_a_returning_person_is_recognised_by_the_permanent_id_even_if_their_user_name_changed(world):
    async def go(db):
        db.add(user(external_identity=f"entra:{TID}:{OID}", email="old.name@liveoak.example"))
        await db.commit()
        person, outcome = await sso.resolve_user(db, sso.load_config(), {**CLAIMS, "preferred_username": "new.name@liveoak.example"})
        assert outcome == "signed_in" and person.email == "old.name@liveoak.example"
        assert len((await db.execute(select(User))).scalars().all()) == 1

    run(go)


def test_the_first_time_an_existing_account_with_the_same_user_name_is_linked_to_the_microsoft_identity(world):
    async def go(db):
        existing = user(role="tenant_admin")
        db.add(existing)
        await db.commit()
        person, outcome = await sso.resolve_user(db, sso.load_config(), CLAIMS)
        assert outcome == "linked" and person.id == existing.id and person.role == "tenant_admin", "a linked account keeps the role it had"
        assert person.external_identity == f"entra:{TID}:{OID}"

    run(go)


def test_an_account_already_linked_to_another_microsoft_identity_is_not_taken_over_by_a_matching_user_name(world):
    async def go(db):
        db.add(user(external_identity=f"entra:{TID}:somebody-else"))
        await db.commit()
        with pytest.raises(sso.SsoFailure) as e:
            await sso.resolve_user(db, sso.load_config(), CLAIMS)
        assert e.value.code == "linked"

    run(go)


def test_a_disabled_account_stays_refused_whether_found_by_the_permanent_id_or_the_user_name(world):
    async def go(db):
        db.add(user(is_active=False))
        await db.commit()
        with pytest.raises(sso.SsoFailure) as e:
            await sso.resolve_user(db, sso.load_config(), CLAIMS)
        assert e.value.code == "disabled"
        db.add(user(account_name="linked.one", email="other@liveoak.example", is_active=False, external_identity=f"entra:{TID}:linked"))
        await db.commit()
        with pytest.raises(sso.SsoFailure) as e2:
            await sso.resolve_user(db, sso.load_config(), {**CLAIMS, "oid": "linked"})
        assert e2.value.code == "disabled"

    run(go)


def test_with_no_home_tenant_set_a_stranger_is_refused_instead_of_created_somewhere_unknown(world):
    world.monkeypatch.delenv("MS_SSO_ACORN_TENANT_ID")

    async def go(db):
        with pytest.raises(sso.SsoFailure) as e:
            await sso.resolve_user(db, sso.load_config(), CLAIMS)
        assert e.value.code == "no_account"

    run(go)


def test_a_token_with_no_user_name_cannot_be_matched_or_created(world):
    async def go(db):
        with pytest.raises(sso.SsoFailure) as e:
            await sso.resolve_user(db, sso.load_config(), {"tid": TID, "oid": OID, "email": "only.email@evil.example"})
        assert e.value.code == "identity"

    run(go)


# ─── The whole sign-in ───────────────────────────────────────────────────────────────────────────────────────────────────

def finish(world, db, *, state, code="auth-code", error=None):
    return sso.microsoft_callback(db, code=code, state=state, error=error)


def test_a_full_sign_in_ends_with_a_one_time_code_that_gives_the_same_tokens_as_a_password_sign_in_once(world):
    async def go(db):
        state, saved = await begin(world, "/cases/7")
        world.token.body = {"id_token": id_token(nonce=saved["nonce"])}
        response = await finish(world, db, state=state)
        assert response.status_code == 302
        target = urlsplit(response.headers["location"])
        assert f"{target.scheme}://{target.netloc}{target.path}" == "https://acorn.example.com/login"
        q = query(response)
        assert q["next"] == "/cases/7" and "sso_error" not in q
        # Microsoft was asked for the tokens with the secret and the verifier, and nothing else leaks to the browser
        sent = world.token.calls[0][1]
        assert sent["client_secret"] == "s3cret-value" and sent["code_verifier"] == saved["verifier"] and sent["code"] == "auth-code"
        assert "s3cret-value" not in response.headers["location"] and "id_token" not in response.headers["location"]
        # the one-time code gives the session tokens, once
        out = await sso.exchange(sso.ExchangeRequest(code=q["sso"]))
        access = decode_token(out.access_token)
        person = (await db.execute(select(User))).scalar_one()
        assert access["sub"] == str(person.id) and access["role"] == "viewer" and access["tenant_id"] == str(HOME)
        assert decode_token(out.refresh_token)["type"] == "refresh"
        with pytest.raises(HTTPException) as again:
            await sso.exchange(sso.ExchangeRequest(code=q["sso"]))
        assert again.value.status_code == 401
        # an audit event says what happened, and the last sign-in time is set
        actions = [c.kwargs["action"] for c in world.audit.await_args_list]
        assert actions == ["auth:sso_user_created"]
        assert person.last_login is not None

    run(go)


def test_the_second_sign_in_is_an_ordinary_sign_in_and_is_audited_as_such(world):
    async def go(db):
        for expected in ("auth:sso_user_created", "auth:sso_login"):
            state, saved = await begin(world)
            world.token.body = {"id_token": id_token(nonce=saved["nonce"])}
            response = await finish(world, db, state=state)
            assert "sso" in query(response)
            assert world.audit.await_args_list[-1].kwargs["action"] == expected
        assert len((await db.execute(select(User))).scalars().all()) == 1

    run(go)


def test_a_state_can_be_used_once_so_a_replayed_callback_signs_nobody_in(world):
    async def go(db):
        state, saved = await begin(world)
        world.token.body = {"id_token": id_token(nonce=saved["nonce"])}
        assert "sso" in query(await finish(world, db, state=state))
        replay = await finish(world, db, state=state)
        assert query(replay) == {"sso_error": "state"}
        assert len(world.token.calls) == 1, "Microsoft was not even asked a second time"

    run(go)


def test_an_unknown_or_missing_state_is_refused_before_anything_is_exchanged(world):
    async def go(db):
        assert query(await finish(world, db, state="never-issued")) == {"sso_error": "state"}
        assert query(await sso.microsoft_callback(db, code="c", state=None, error=None)) == {"sso_error": "state"}
        assert world.token.calls == []

    run(go)


def test_microsoft_saying_no_or_sending_no_code_ends_at_the_login_page_and_uses_up_the_state(world):
    async def go(db):
        state, _ = await begin(world)
        assert query(await finish(world, db, state=state, code=None, error="access_denied")) == {"sso_error": "denied"}
        assert f"aisoc:sso:state:{state}" not in world.redis.data
        state2, _ = await begin(world)
        assert query(await sso.microsoft_callback(db, code=None, state=state2, error=None)) == {"sso_error": "denied"}

    run(go)


def test_a_refused_code_exchange_or_one_with_no_id_token_signs_nobody_in(world):
    async def go(db):
        state, _ = await begin(world)
        world.token.status, world.token.body = 400, {"error": "invalid_grant"}
        assert query(await finish(world, db, state=state)) == {"sso_error": "token"}
        state, _ = await begin(world)
        world.token.status, world.token.body = 200, {"access_token": "x"}
        assert query(await finish(world, db, state=state)) == {"sso_error": "token"}
        assert (await db.execute(select(User))).scalars().all() == []

    run(go)


def test_a_forged_foreign_or_wrong_tenant_token_signs_nobody_in_and_creates_nothing(world):
    async def go(db):
        for token, code in (
            (id_token(key=OTHER_KEY), "token"),
            (id_token(aud="other-app"), "token"),
            (id_token(tid="99999999-0000-0000-0000-000000000000"), "tenant"),
        ):
            state, saved = await begin(world)
            world.token.body = {"id_token": token}
            response = await finish(world, db, state=state)
            assert query(response) == {"sso_error": code}, code
        assert (await db.execute(select(User))).scalars().all() == []
        assert world.audit.await_count == 0

    run(go)


def test_a_person_outside_the_allowed_group_is_refused_and_not_created(world):
    world.monkeypatch.setenv("MS_SSO_GROUP_ID", GROUP)

    async def go(db):
        state, saved = await begin(world)
        world.token.body = {"id_token": id_token(nonce=saved["nonce"], groups=["someone-elses-group"])}
        assert query(await finish(world, db, state=state)) == {"sso_error": "group"}
        assert (await db.execute(select(User))).scalars().all() == []
        state, saved = await begin(world)
        world.token.body = {"id_token": id_token(nonce=saved["nonce"], groups=[GROUP])}
        assert "sso" in query(await finish(world, db, state=state))

    run(go)


def test_a_disabled_account_is_refused_at_the_end_and_gets_no_code(world):
    async def go(db):
        db.add(user(is_active=False, external_identity=f"entra:{TID}:{OID}"))
        await db.commit()
        state, saved = await begin(world)
        world.token.body = {"id_token": id_token(nonce=saved["nonce"])}
        assert query(await finish(world, db, state=state)) == {"sso_error": "disabled"}
        assert not [k for k in world.redis.data if "code" in k]

    run(go)


def test_microsoft_being_unreachable_says_unavailable_and_changes_nothing(world):
    async def go(db):
        state, _ = await begin(world)

        async def down(url, data):
            raise OSError("no route")

        world.monkeypatch.setattr(sso, "_post_form", down)
        assert query(await finish(world, db, state=state)) == {"sso_error": "unavailable"}
        assert (await db.execute(select(User))).scalars().all() == []

    run(go)


def test_the_exchange_refuses_a_made_up_or_expired_code_and_says_so_if_the_store_is_down(world):
    async def go(db):
        with pytest.raises(HTTPException) as e:
            await sso.exchange(sso.ExchangeRequest(code="made-up"))
        assert e.value.status_code == 401
        world.redis.down = True
        with pytest.raises(HTTPException) as e2:
            await sso.exchange(sso.ExchangeRequest(code="x"))
        assert e2.value.status_code == 503

    run(go)


def test_the_callback_when_off_answers_501(monkeypatch):
    monkeypatch.delenv("MS_SSO_TENANT_ID", raising=False)

    async def go(db):
        with pytest.raises(HTTPException) as e:
            await sso.microsoft_callback(db, code="c", state="s", error=None)
        assert e.value.status_code == 501

    run(go)

"""Sign in with Microsoft (Entra ID) for the people of one Microsoft tenant.

OFF unless MS_SSO_TENANT_ID, MS_SSO_CLIENT_ID, MS_SSO_CLIENT_SECRET and MS_SSO_REDIRECT_URI are all set. Everything is decided here, on the server; the browser is only sent to Microsoft and back.

The flow (authorization code with PKCE):
  1. GET  /auth/sso/microsoft/login     -> a state, a nonce and a PKCE verifier are kept for ten minutes (Redis); the browser is sent to Microsoft.
  2. GET  /auth/sso/microsoft/callback  <- Microsoft sends the browser back with ?code and ?state. The state is used up. The code is traded (with the client secret) for an ID token, which is checked:
        signature (Microsoft's published keys), issuer, audience, expiry, nonce and the Microsoft TENANT it came from; then, if MS_SSO_GROUP_ID is set, that the person is in that group.
     Then the person is found or made (see resolve_user) and a one-time code is made for the browser; the browser is sent to /login?sso=<code>.
  3. POST /auth/sso/exchange            -> the one-time code (valid a minute, usable once) is traded for the same access and refresh tokens that password sign-in gives.

Who the person is: by Microsoft's own permanent id for them (the ``oid`` claim, kept with the tenant id as ``entra:<tid>:<oid>``), never by the email claim, which a person can sometimes edit. The FIRST time, an existing
account with the same user name (``preferred_username``, the UPN) and no Microsoft link yet is linked; with no such account one is created with MS_SSO_NEW_USER_ROLE (viewer unless set, and never an administrator
role) in MS_SSO_ACORN_TENANT_ID. A disabled account stays refused.

Password sign-in: with MS_SSO_PASSWORD_LOGIN=admins (the default once SSO is on) only administrator roles may still sign in with a password, as a way back in if Microsoft or this setup breaks; MS_SSO_PASSWORD_LOGIN=all keeps it for
everyone. See password_login_allowed, used by /auth/login.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
import jwt as pyjwt
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel
from redis.asyncio import Redis, from_url
from redis.exceptions import RedisError
from sqlalchemy import select, update

from app.api.v1.deps import DBSession
from app.core.config import settings
from app.core.emails import normalize_email
from app.core.security import ROLE_PERMISSIONS, create_access_token, create_refresh_token, get_password_hash
from app.models.rbac import Role, UserRole
from app.models.tenant import Tenant, User
from app.services.account_names import unique_account_name
from app.services.audit import emit_audit
from app.services.sso_default_role import effective as effective_default_role
from app.services.user_lookup import find_user_by_email

logger = logging.getLogger("aisoc.sso.microsoft")
router = APIRouter(prefix="/auth/sso", tags=["auth-sso"])

AUTHORITY = "https://login.microsoftonline.com"
STATE_TTL = 600
CODE_TTL = 60
KEYS_TTL = 3600
ADMIN_ROLES = frozenset({"platform_admin", "admin", "tenant_admin"})
# Roles that a new person may never be created with, whatever the setting says.
NEVER_AT_FIRST = ADMIN_ROLES | {"api_service"}


# ─── Settings ────────────────────────────────────────────────────────────────────────────────────────────────────────────

class SsoConfig(BaseModel):
    tenant_id: str
    client_id: str
    client_secret: str
    redirect_uri: str
    group_id: str | None = None
    home_tenant: uuid.UUID | None = None
    new_user_role: str = "viewer"
    password_login: str = "admins"
    web_url: str


def load_config(env: dict[str, str] | None = None) -> SsoConfig | None:
    """The settings, or None when SSO is not (fully) configured."""
    e = env if env is not None else os.environ
    tenant, client, secret, redirect = (e.get(k, "").strip() for k in ("MS_SSO_TENANT_ID", "MS_SSO_CLIENT_ID", "MS_SSO_CLIENT_SECRET", "MS_SSO_REDIRECT_URI"))
    if not (tenant and client and secret and redirect):
        return None
    home: uuid.UUID | None = None
    raw_home = e.get("MS_SSO_ACORN_TENANT_ID", "").strip()
    if raw_home:
        try:
            home = uuid.UUID(raw_home)
        except ValueError:
            home = None
    role = e.get("MS_SSO_NEW_USER_ROLE", "viewer").strip() or "viewer"
    if role not in ROLE_PERMISSIONS or role in NEVER_AT_FIRST:
        role = "viewer"
    policy = e.get("MS_SSO_PASSWORD_LOGIN", "admins").strip().lower()
    parts = urlsplit(redirect)
    web = e.get("MS_SSO_WEB_URL", "").strip().rstrip("/") or f"{parts.scheme}://{parts.netloc}"
    return SsoConfig(
        tenant_id=tenant,
        client_id=client,
        client_secret=secret,
        redirect_uri=redirect,
        group_id=(e.get("MS_SSO_GROUP_ID", "").strip() or None),
        home_tenant=home,
        new_user_role=role,
        password_login="all" if policy == "all" else "admins",
        web_url=web,
    )


def password_login_allowed(role: str, env: dict[str, str] | None = None) -> bool:
    """Whether a person with this role may still sign in with a password. Always yes while SSO is off; once on, only administrators (unless the setting says everyone)."""
    cfg = load_config(env)
    if cfg is None or cfg.password_login == "all":
        return True
    return role in ADMIN_ROLES


# ─── Redis (state and one-time codes) ──────────────────────────────────────────────────────────────────────────────────────

_redis: Redis | None = None


def _store() -> Redis:
    global _redis
    if _redis is None:
        _redis = from_url(str(settings.REDIS_URL), decode_responses=True, socket_connect_timeout=1.0, socket_timeout=1.0)
    return _redis


class Unavailable(Exception):
    """The short-lived store (Redis) cannot be reached."""


async def _put(key: str, value: dict[str, Any], ttl: int) -> None:
    try:
        await _store().set(key, json.dumps(value), ex=ttl)
    except (RedisError, OSError) as exc:
        logger.warning("sso.store_unavailable err=%s", exc)
        raise Unavailable from exc


async def _take(key: str) -> dict[str, Any] | None:
    """Read and delete in one step, so a state or a code can be used once."""
    try:
        raw = await _store().getdel(key)
    except (RedisError, OSError) as exc:
        logger.warning("sso.store_unavailable err=%s", exc)
        raise Unavailable from exc
    if not raw:
        return None
    try:
        out = json.loads(raw)
    except ValueError:
        return None
    return out if isinstance(out, dict) else None


# ─── Talking to Microsoft ─────────────────────────────────────────────────────────────────────────────────────────────────

_keys_cache: dict[str, tuple[float, dict[str, Any]]] = {}


async def _get_json(url: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(url, headers={"Accept": "application/json"})
        response.raise_for_status()
        return dict(response.json())


async def _post_form(url: str, data: dict[str, str]) -> tuple[int, dict[str, Any]]:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(url, data=data, headers={"Accept": "application/json"})
        try:
            body = response.json()
        except ValueError:
            body = {}
        return response.status_code, body if isinstance(body, dict) else {}


def _issuer(tenant_id: str) -> str:
    return f"{AUTHORITY}/{tenant_id}/v2.0"


async def _signing_keys(tenant_id: str, *, refresh: bool = False) -> dict[str, Any]:
    """Microsoft's published signing keys for the tenant, by key id (kept an hour; fetched again once when an unknown key id turns up)."""
    cached = _keys_cache.get(tenant_id)
    if cached and not refresh and time.time() - cached[0] < KEYS_TTL:
        return cached[1]
    discovery = await _get_json(f"{AUTHORITY}/{tenant_id}/v2.0/.well-known/openid-configuration")
    jwks = await _get_json(str(discovery["jwks_uri"]))
    keys = {k["kid"]: k for k in jwks.get("keys", []) if isinstance(k, dict) and k.get("kid")}
    _keys_cache[tenant_id] = (time.time(), keys)
    return keys


class SsoFailure(Exception):
    """Why a sign-in was refused: ``code`` is a short word for the login page, ``detail`` is for the log only."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


async def verify_id_token(cfg: SsoConfig, id_token: str, nonce: str) -> dict[str, Any]:
    """The claims of an ID token that is genuinely Microsoft's, for this app, for this tenant and for this sign-in; otherwise an SsoFailure."""
    try:
        header = pyjwt.get_unverified_header(id_token)
    except pyjwt.PyJWTError as exc:
        raise SsoFailure("token", f"unreadable id token: {exc}") from None
    if header.get("alg") != "RS256":  # never accept "none" or a symmetric algorithm
        raise SsoFailure("token", f"unexpected algorithm {header.get('alg')!r}")
    kid = header.get("kid")
    keys = await _signing_keys(cfg.tenant_id)
    if kid not in keys:
        keys = await _signing_keys(cfg.tenant_id, refresh=True)
    if kid not in keys:
        raise SsoFailure("token", "unknown signing key")
    try:
        claims = pyjwt.decode(
            id_token,
            pyjwt.PyJWK.from_dict(keys[kid]).key,
            algorithms=["RS256"],
            audience=cfg.client_id,
            issuer=_issuer(cfg.tenant_id),
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            leeway=60,
        )
    except pyjwt.PyJWTError as exc:
        raise SsoFailure("token", f"id token refused: {exc}") from None
    if claims.get("tid") != cfg.tenant_id:
        raise SsoFailure("tenant", f"wrong tenant {claims.get('tid')!r}")
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise SsoFailure("token", "nonce mismatch")
    if not claims.get("oid"):
        raise SsoFailure("token", "no oid claim")
    return dict(claims)


def check_group(cfg: SsoConfig, claims: dict[str, Any]) -> None:
    """With a group configured, the person must be in it. Fail closed: a missing groups claim (or Microsoft's "too many groups" marker) is a refusal, never a pass."""
    if not cfg.group_id:
        return
    groups = claims.get("groups")
    if isinstance(groups, list):
        if cfg.group_id.lower() in {str(g).lower() for g in groups}:
            return
        raise SsoFailure("group", "not in the allowed group")
    if "groups" in (claims.get("_claim_names") or {}):
        raise SsoFailure("group", "group overage: too many groups to list in the token; assign the group to the application instead")
    raise SsoFailure("group", "no groups claim in the token")


# ─── People ───────────────────────────────────────────────────────────────────────────────────────────────────────────────

def identity_key(claims: dict[str, Any]) -> str:
    return f"entra:{claims['tid']}:{claims['oid']}"


def upn_of(claims: dict[str, Any]) -> str:
    # The user name (UPN) only. The "email" claim is deliberately not used: in some setups the person can edit it, so it cannot be trusted to say who they are.
    return normalize_email(str(claims.get("preferred_username") or claims.get("upn") or "")) or ""


async def resolve_user(db: Any, cfg: SsoConfig, claims: dict[str, Any]) -> tuple[User, str]:
    """The account for this Microsoft identity, and what happened (``signed_in``, ``linked`` or ``created``). Raises SsoFailure when the person may not come in."""
    key = identity_key(claims)
    upn = upn_of(claims)
    user = (await db.execute(select(User).where(User.external_identity == key))).scalar_one_or_none()
    if user is not None:
        if not user.is_active:
            raise SsoFailure("disabled", "account disabled")
        return user, "signed_in"
    if not upn:
        raise SsoFailure("identity", "no user name in the token")
    existing = await find_user_by_email(db, upn)
    if existing is not None:
        if not existing.is_active:
            raise SsoFailure("disabled", "account disabled")
        if existing.external_identity and existing.external_identity != key:
            raise SsoFailure("linked", "account linked to a different Microsoft identity")
        existing.external_identity = key
        return existing, "linked"
    if cfg.home_tenant is None:
        raise SsoFailure("no_account", "no account, and automatic creation is not set up (MS_SSO_ACORN_TENANT_ID)")
    name = str(claims.get("name") or "").strip()[:100] or upn.split("@")[0]
    account_name = await unique_account_name(db, upn.split("@")[0])
    # The role chosen under Settings > Roles & Permissions, else the server setting. Never an administrator role, whatever is stored.
    home = await db.get(Tenant, cfg.home_tenant)
    role, custom_role_id, _ = effective_default_role(home.settings if home is not None else None, cfg.new_user_role)
    if role not in ROLE_PERMISSIONS or role in NEVER_AT_FIRST:
        role, custom_role_id = "viewer", None
    created = User(
        tenant_id=cfg.home_tenant,
        email=upn,
        account_name=account_name,
        username=name,
        # Nobody knows this password: sign-in is through Microsoft until an administrator sets one.
        hashed_password=get_password_hash(secrets.token_urlsafe(48)),
        role=role,
        is_active=True,
        is_verified=True,
        external_identity=key,
    )
    db.add(created)
    await db.flush()
    if custom_role_id is not None:
        # Only a role of this workspace; one that was deleted since is simply not given.
        if (await db.execute(select(Role.id).where(Role.id == custom_role_id, Role.tenant_id == cfg.home_tenant))).first() is not None:
            db.add(UserRole(user_id=created.id, role_id=custom_role_id))
    return created, "created"


def tokens_for(user: User) -> dict[str, str]:
    data = {
        "sub": str(user.id),
        "tenant_id": str(user.tenant_id),
        "role": user.role,
        "email": user.email or user.account_name,
        "account_name": user.account_name,
    }
    return {"access_token": create_access_token(data), "refresh_token": create_refresh_token(data)}


# ─── Routes ───────────────────────────────────────────────────────────────────────────────────────────────────────────────

def safe_next(value: str | None) -> str:
    """Only a path on this site: anything else (another site, a scheme, a protocol-relative address, a backslash trick) becomes the front page."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value or "\n" in value or "\r" in value:
        return "/"
    return value[:300]


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


class SsoStatus(BaseModel):
    microsoft: bool
    password_login: str


@router.get("/status", response_model=SsoStatus)
async def sso_status() -> SsoStatus:
    """Which ways of signing in the login page offers. Public: it only says whether the Microsoft button is shown and whether passwords still work for everyone."""
    cfg = load_config()
    return SsoStatus(microsoft=cfg is not None, password_login=cfg.password_login if cfg else "all")


@router.get("/microsoft/login")
async def microsoft_login(next: str | None = Query(default=None, max_length=300)) -> Response:  # noqa: A002
    cfg = load_config()
    if cfg is None:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Sign in with Microsoft is not set up.")
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier, challenge = _pkce()
    try:
        await _put(f"aisoc:sso:state:{state}", {"nonce": nonce, "verifier": verifier, "next": safe_next(next)}, STATE_TTL)
    except Unavailable:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Sign-in is temporarily unavailable. Try again in a moment.") from None
    query = urlencode(
        {
            "client_id": cfg.client_id,
            "response_type": "code",
            "redirect_uri": cfg.redirect_uri,
            "response_mode": "query",
            "scope": "openid profile email",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    return RedirectResponse(f"{AUTHORITY}/{cfg.tenant_id}/oauth2/v2.0/authorize?{query}", status_code=302)


def _back_to_login(cfg: SsoConfig, **params: str) -> RedirectResponse:
    return RedirectResponse(f"{cfg.web_url}/login?{urlencode(params)}", status_code=302)


@router.get("/microsoft/callback")
async def microsoft_callback(
    db: DBSession,
    code: str | None = Query(default=None, max_length=4000),
    state: str | None = Query(default=None, max_length=200),
    error: str | None = Query(default=None, max_length=200),
) -> Response:
    cfg = load_config()
    if cfg is None:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Sign in with Microsoft is not set up.")
    if not state:
        return _back_to_login(cfg, sso_error="state")
    try:
        saved = await _take(f"aisoc:sso:state:{state}")
    except Unavailable:
        return _back_to_login(cfg, sso_error="unavailable")
    if saved is None:  # unknown, already used or expired: a replay or a stale tab
        return _back_to_login(cfg, sso_error="state")
    if error or not code:
        logger.info("sso.microsoft_refused error=%s", (error or "no code")[:60])
        return _back_to_login(cfg, sso_error="denied")

    try:
        status_code, tokens = await _post_form(
            f"{AUTHORITY}/{cfg.tenant_id}/oauth2/v2.0/token",
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": cfg.redirect_uri,
                "client_id": cfg.client_id,
                "client_secret": cfg.client_secret,
                "code_verifier": str(saved.get("verifier", "")),
                "scope": "openid profile email",
            },
        )
    except (httpx.HTTPError, OSError) as exc:
        logger.warning("sso.token_exchange_unreachable err=%s", type(exc).__name__)
        return _back_to_login(cfg, sso_error="unavailable")
    if status_code != 200 or not tokens.get("id_token"):
        logger.warning("sso.token_exchange_refused status=%s error=%s", status_code, str(tokens.get("error"))[:60])
        return _back_to_login(cfg, sso_error="token")

    try:
        claims = await verify_id_token(cfg, str(tokens["id_token"]), str(saved.get("nonce", "")))
        check_group(cfg, claims)
        user, outcome = await resolve_user(db, cfg, claims)
    except SsoFailure as failure:
        logger.warning("sso.microsoft_refused reason=%s detail=%s", failure.code, str(failure)[:160])
        await db.rollback()
        return _back_to_login(cfg, sso_error=failure.code)
    except (httpx.HTTPError, OSError, KeyError) as exc:
        logger.warning("sso.microsoft_unavailable err=%s", type(exc).__name__)
        await db.rollback()
        return _back_to_login(cfg, sso_error="unavailable")

    await db.execute(update(User).where(User.id == user.id).values(last_login=datetime.now(UTC)))
    await emit_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_id=user.id,
        actor_email=user.email,
        action={"signed_in": "auth:sso_login", "linked": "auth:sso_linked", "created": "auth:sso_user_created"}[outcome],
        resource="user",
        resource_id=str(user.id),
        changes={"provider": "microsoft", "role": user.role} if outcome == "created" else {"provider": "microsoft"},
    )
    await db.commit()

    one_time = secrets.token_urlsafe(32)
    try:
        await _put(f"aisoc:sso:code:{one_time}", tokens_for(user), CODE_TTL)
    except Unavailable:
        return _back_to_login(cfg, sso_error="unavailable")
    return _back_to_login(cfg, sso=one_time, next=safe_next(str(saved.get("next", "/"))))


class ExchangeRequest(BaseModel):
    code: str


class ExchangeResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


@router.post("/exchange", response_model=ExchangeResponse)
async def exchange(body: ExchangeRequest) -> ExchangeResponse:
    """Trade the one-time code from the redirect for the session tokens. A code works once and for a minute."""
    try:
        tokens = await _take(f"aisoc:sso:code:{body.code[:200]}")
    except Unavailable:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Sign-in is temporarily unavailable. Try again in a moment.") from None
    if tokens is None or "access_token" not in tokens:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="That sign-in link has expired or was already used. Start again.")
    return ExchangeResponse(access_token=str(tokens["access_token"]), refresh_token=str(tokens["refresh_token"]))

"""Web push for a critical alert (roadmap r7-af-39): turn notifications on for this browser, off again, and send a test. A signed-in person only, as in ``push.py`` (the gateway of the removed phone app, which this does not touch): a push subscription belongs to a person's device.

The browser asks for the organization's public key, subscribes with it, and sends the subscription here. A critical alert is then pushed by ``app.workers.push_alert_worker``.
"""

from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.api.v1.deps import DBSession, SessionUser, require_permission
from app.models.push import PushSubscription
from app.services import push_notify as pn
from app.services import web_push as wp

router = APIRouter(prefix="/alert-push", tags=["push"])
MAX_SUBSCRIPTIONS_PER_USER = 10


class Keys(BaseModel):
    p256dh: str = Field(min_length=20, max_length=200)
    auth: str = Field(min_length=8, max_length=100)


class SubscribeIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=2000)
    keys: Keys


class UnsubscribeIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=2000)


def _check_endpoint(endpoint: str) -> None:
    parts = urlsplit(endpoint)
    if parts.scheme != "https" or not parts.netloc:
        raise HTTPException(status_code=422, detail="A push address must be an https address.")


@router.get("/public-key", dependencies=[Depends(require_permission("alerts:read"))], summary="The key a browser needs to turn notifications on")
async def public_key(user: SessionUser, db: DBSession) -> dict[str, str]:
    key = await pn.ensure_key(db, user.tenant_id)
    await db.commit()
    return {"public_key": key.public_key}


@router.post("/subscribe", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_permission("alerts:read"))], summary="Turn notifications on for this browser")
async def subscribe(body: SubscribeIn, user: SessionUser, db: DBSession) -> None:
    _check_endpoint(body.endpoint)
    mine = (await db.execute(select(PushSubscription).where(PushSubscription.tenant_id == user.tenant_id, PushSubscription.user_id == user.user_id))).scalars().all()
    existing = next((s for s in mine if s.endpoint == body.endpoint), None)
    if existing is not None:
        existing.p256dh, existing.auth = body.keys.p256dh, body.keys.auth
    else:
        if len(mine) >= MAX_SUBSCRIPTIONS_PER_USER:
            raise HTTPException(status_code=400, detail="That is the most browsers one person can turn notifications on for. Turn one off first.")
        db.add(PushSubscription(tenant_id=user.tenant_id, user_id=user.user_id, endpoint=body.endpoint, p256dh=body.keys.p256dh, auth=body.keys.auth))
    await db.commit()


@router.post("/unsubscribe", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_permission("alerts:read"))], summary="Turn notifications off for this browser")
async def unsubscribe(body: UnsubscribeIn, user: SessionUser, db: DBSession) -> None:
    await db.execute(delete(PushSubscription).where(PushSubscription.tenant_id == user.tenant_id, PushSubscription.user_id == user.user_id, PushSubscription.endpoint == body.endpoint))
    await db.commit()


@router.post("/test", dependencies=[Depends(require_permission("alerts:read"))], summary="Send a test notification to the browsers you turned on")
async def test_push(user: SessionUser, db: DBSession) -> dict[str, Any]:
    async with httpx.AsyncClient() as http:

        async def sender(endpoint: str, p256dh: str, auth: str, payload: bytes, private: str, public: str) -> int:
            return await wp.send(http, endpoint, p256dh, auth, payload, private, public, pn.SUBJECT)

        out = await pn.send_to_tenant(db, user.tenant_id, wp.alert_message("Test", "Notifications are working.", "critical"), sender)
    await db.commit()
    return out

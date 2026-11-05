"""``GET /alerts/{id}/why``: the facts behind one alert (which tool and rule raised it and what it names). Read only."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.models.alert import Alert
from app.services.alert_scope import alert_scope
from app.services.alert_why import why_raised

router = APIRouter(prefix="/alerts", tags=["alerts"])


class WhyRow(BaseModel):
    label: str
    value: str


class Why(BaseModel):
    facts: list[WhyRow]


@router.get(
    "/{alert_id}/why",
    response_model=Why,
    dependencies=[Depends(require_permission("alerts:read"))],
    summary="Why this alert was raised: the tool, the rule, how sure it was and what it names",
)
async def alert_why(alert_id: uuid.UUID, user: AuthUser, db: DBSession) -> Why:
    async with alert_scope(db, user.tenant_id, alert_id) as tid:
        alert = (await db.execute(select(Alert).where(Alert.id == alert_id, Alert.tenant_id == tid))).scalar_one_or_none()
        if alert is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
        return Why(facts=[WhyRow(**r) for r in why_raised(alert)])

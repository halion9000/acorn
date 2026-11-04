"""What the platform keeps and for how long (``GET /data-retention``): a plain-words list built from the live settings, so a client's question has an answer that is always true."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.v1.deps import AuthUser, require_permission
from app.core.config import settings
from app.services.data_retention import retention_lines

router = APIRouter(prefix="/data-retention", tags=["settings"])


class RetentionLine(BaseModel):
    what: str
    kept: str
    ends: str


@router.get("", response_model=list[RetentionLine])
async def data_retention(_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))]) -> list[RetentionLine]:
    """Each kind of data, how long it is kept, and what ends it. Read only."""
    return [RetentionLine(**line) for line in retention_lines(settings)]

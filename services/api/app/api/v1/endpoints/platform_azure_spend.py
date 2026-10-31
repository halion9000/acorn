"""What the Azure resources running A.C.O.R.N cost this month (PLATFORM ADMINISTRATORS ONLY).

Every route requires `platform:cross_tenant_query`, which only the platform_admin role holds. It is read-only: the server reads Azure Cost Management with its own managed identity (see app/services/azure_spend.py) and
returns totals, never any credential. Nothing here is tenant data.
"""

from __future__ import annotations

import os
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.v1.deps import AuthUser, require_permission
from app.services import azure_spend

router = APIRouter(prefix="/platform/azure-spend", tags=["platform"])


class AzureSpend(BaseModel):
    configured: bool
    currency: str = "USD"
    month: str = ""
    total: float = 0.0
    by_service: list[dict[str, Any]] = []
    daily: list[dict[str, Any]] = []
    forecast: float | None = None
    budget: float | None = None
    fetched_at: str | None = None
    stale: bool = False
    error: str | None = None


@router.get("", response_model=AzureSpend)
async def get_azure_spend(
    current_user: Annotated[AuthUser, Depends(require_permission("platform:cross_tenant_query"))],
    refresh: Annotated[bool, Query()] = False,
) -> AzureSpend:
    spend = await azure_spend.get_spend(dict(os.environ), refresh=refresh)
    return AzureSpend(**spend.__dict__)

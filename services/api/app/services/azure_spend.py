"""Azure spend for the Settings page: what the Azure resources running A.C.O.R.N cost this month.

READ ONLY. The API signs in with the VM's own managed identity (no stored secret) and asks Azure Cost Management for this month's actual cost, by service and by day. The identity needs only
the built-in role "Cost Management Reader" on the scope (the resource group). Set ACORN_AZURE_SPEND_SCOPE (for example /subscriptions/<id>/resourceGroups/<group>) to turn it on; without it the page says
how. ACORN_AZURE_SPEND_BUDGET (a number, optional) adds a budget comparison; with none set, no budget is shown or assumed.

Azure rate-limits this query hard (HTTP 429) and posts charges with a delay of hours to a day, so the answer is kept for CACHE_SECONDS, the last good answer is served (marked stale) when a refresh fails,
and a manual refresh is allowed once every MIN_REFRESH_SECONDS.
"""

from __future__ import annotations

import calendar
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import httpx

CACHE_SECONDS = 6 * 3600
MIN_REFRESH_SECONDS = 600
_IMDS = "http://169.254.169.254/metadata/identity/oauth2/token"
_QUERY = "https://management.azure.com{scope}/providers/Microsoft.CostManagement/query?api-version=2023-11-01"


@dataclass
class Spend:
    configured: bool
    currency: str = "USD"
    month: str = ""
    total: float = 0.0
    by_service: list[dict[str, Any]] = field(default_factory=list)
    daily: list[dict[str, Any]] = field(default_factory=list)
    forecast: float | None = None
    budget: float | None = None
    fetched_at: str | None = None
    stale: bool = False
    error: str | None = None


def settings_from(env: dict[str, str]) -> tuple[str | None, float | None]:
    """The scope (a subscription or resource-group path) and the optional budget. A malformed scope or budget counts as not set."""
    scope = env.get("ACORN_AZURE_SPEND_SCOPE", "").strip().rstrip("/")
    if not scope.lower().startswith("/subscriptions/") or " " in scope or ".." in scope:
        scope = ""
    try:
        budget = float(env.get("ACORN_AZURE_SPEND_BUDGET", "").strip())
        budget = budget if budget > 0 else None
    except ValueError:
        budget = None
    return (scope or None), budget


def _table(payload: dict[str, Any]) -> list[dict[str, Any]]:
    props = payload.get("properties") or {}
    names = [c.get("name") for c in props.get("columns") or []]
    return [dict(zip(names, row, strict=False)) for row in props.get("rows") or []]


def parse(by_service_payload: dict[str, Any], daily_payload: dict[str, Any], today: date, budget: float | None) -> Spend:
    """Turns the two Cost Management answers into the screen's numbers. Costs are rounded to cents; nothing is invented when Azure has posted nothing yet."""
    services = _table(by_service_payload)
    days = _table(daily_payload)
    currency = next((str(r["Currency"]) for r in services + days if r.get("Currency")), "USD")
    by_service = sorted(
        ({"service": str(r.get("ServiceName") or "Other"), "cost": round(float(r.get("Cost") or 0), 2)} for r in services),
        key=lambda r: -r["cost"],
    )
    daily = sorted(
        (
            {"date": f"{str(r['UsageDate'])[:4]}-{str(r['UsageDate'])[4:6]}-{str(r['UsageDate'])[6:8]}", "cost": round(float(r.get("Cost") or 0), 2)}
            for r in days
            if r.get("UsageDate")
        ),
        key=lambda r: r["date"],
    )
    total = round(sum(r["cost"] for r in by_service), 2)
    # A simple projection: the average of the days that have charges, over the whole month. Days Azure has not posted yet are left out, so the forecast is a floor early in the month.
    posted = [d["cost"] for d in daily if d["cost"] > 0]
    forecast = None
    if posted:
        forecast = round(sum(posted) / len(posted) * calendar.monthrange(today.year, today.month)[1], 2)
    return Spend(
        configured=True,
        currency=currency,
        month=today.strftime("%Y-%m"),
        total=total,
        by_service=by_service,
        daily=daily,
        forecast=forecast,
        budget=budget,
    )


Post = Callable[..., Awaitable[httpx.Response]]
Get = Callable[..., Awaitable[httpx.Response]]


async def _token(get: Get) -> str:
    response = await get(_IMDS, params={"api-version": "2018-02-01", "resource": "https://management.azure.com/"}, headers={"Metadata": "true"})
    if response.status_code != 200:
        raise RuntimeError("This server has no Azure identity to read costs with (is it an Azure VM with a managed identity?)")
    return str(response.json()["access_token"])


async def _query(post: Post, token: str, scope: str, grouping: str | None, granularity: str) -> dict[str, Any]:
    dataset: dict[str, Any] = {"granularity": granularity, "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}}}
    if grouping:
        dataset["grouping"] = [{"type": "Dimension", "name": grouping}]
    body = {"type": "ActualCost", "timeframe": "MonthToDate", "dataset": dataset}
    response = await post(_QUERY.format(scope=scope), json=body, headers={"Authorization": f"Bearer {token}"})
    if response.status_code == 403:
        raise RuntimeError('Azure refused the cost request: give this server\'s identity the "Cost Management Reader" role on the resource group.')
    if response.status_code == 429:
        raise RuntimeError("Azure is rate-limiting cost requests; showing the last answer. Try again in a few minutes.")
    if response.status_code != 200:
        raise RuntimeError(f"Azure cost request failed (HTTP {response.status_code}).")
    return dict(response.json())


_cache: tuple[float, Spend] | None = None


def reset_cache() -> None:
    global _cache
    _cache = None


async def get_spend(
    env: dict[str, str],
    *,
    refresh: bool = False,
    get: Get | None = None,
    post: Post | None = None,
    now: Callable[[], float] = time.time,
    today: Callable[[], date] = lambda: datetime.now(UTC).date(),
) -> Spend:
    global _cache
    scope, budget = settings_from(env)
    if scope is None:
        return Spend(configured=False)
    age = now() - _cache[0] if _cache else None
    if _cache and age is not None and (age < CACHE_SECONDS and not refresh or refresh and age < MIN_REFRESH_SECONDS):
        return _cache[1]
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            token = await _token(get or client.get)
            by_service = await _query(post or client.post, token, scope, "ServiceName", "None")
            daily = await _query(post or client.post, token, scope, None, "Daily")
        except (RuntimeError, httpx.HTTPError) as error:
            message = str(error) if isinstance(error, RuntimeError) else "Could not reach Azure to read costs."
            if _cache:
                old = _cache[1]
                return Spend(**{**old.__dict__, "stale": True, "error": message})
            return Spend(configured=True, error=message)
    result = parse(by_service, daily, today(), budget)
    result.fetched_at = datetime.fromtimestamp(now(), UTC).isoformat()
    _cache = (now(), result)
    return result

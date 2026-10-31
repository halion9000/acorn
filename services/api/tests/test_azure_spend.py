"""The Azure spend numbers: what is read, how it is turned into the screen's figures, and what happens when Azure refuses, rate-limits or has posted nothing yet."""

from datetime import date

import pytest
from app.services import azure_spend as az

SCOPE = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test"
ENV = {"ACORN_AZURE_SPEND_SCOPE": SCOPE}

BY_SERVICE = {
    "properties": {
        "columns": [{"name": "Cost"}, {"name": "ServiceName"}, {"name": "Currency"}],
        "rows": [[10.004, "Virtual Network", "USD"], [150.126, "Virtual Machines", "USD"], [30.0, "Azure Database for PostgreSQL", "USD"]],
    }
}
DAILY = {
    "properties": {
        "columns": [{"name": "Cost"}, {"name": "UsageDate"}, {"name": "Currency"}],
        "rows": [[8.0, 20261002, "USD"], [0.0, 20261003, "USD"], [12.0, 20261001, "USD"]],
    }
}


class Reply:
    def __init__(self, status_code=200, payload=None):
        self.status_code, self._payload = status_code, payload or {}

    def json(self):
        return self._payload


class Azure:
    """Records the calls and answers like Azure: an identity token, then the two cost queries."""

    def __init__(self, token=Reply(200, {"access_token": "tok"}), cost=None):
        self.token, self.cost, self.calls, self.bodies = token, list(cost or [Reply(200, BY_SERVICE), Reply(200, DAILY)]), [], []

    async def get(self, url, **kw):
        self.calls.append(("get", url, kw.get("headers", {})))
        return self.token

    async def post(self, url, **kw):
        self.calls.append(("post", url, kw.get("headers", {})))
        self.bodies.append(kw["json"])
        return self.cost.pop(0) if self.cost else Reply(200, DAILY)


@pytest.fixture(autouse=True)
def _fresh_cache():
    az.reset_cache()
    yield
    az.reset_cache()


def test_settings_need_a_real_scope_and_a_positive_budget_only_if_given():
    assert az.settings_from({}) == (None, None)
    assert az.settings_from({"ACORN_AZURE_SPEND_SCOPE": "rg-test"}) == (None, None)
    assert az.settings_from({"ACORN_AZURE_SPEND_SCOPE": "/subscriptions/x/../y"}) == (None, None)
    assert az.settings_from({"ACORN_AZURE_SPEND_SCOPE": SCOPE + "/"}) == (SCOPE, None)
    assert az.settings_from({**ENV, "ACORN_AZURE_SPEND_BUDGET": "500"}) == (SCOPE, 500.0)
    assert az.settings_from({**ENV, "ACORN_AZURE_SPEND_BUDGET": "0"})[1] is None
    assert az.settings_from({**ENV, "ACORN_AZURE_SPEND_BUDGET": "lots"})[1] is None


def test_parse_orders_services_and_days_and_projects_from_the_days_that_have_charges():
    spend = az.parse(BY_SERVICE, DAILY, date(2026, 10, 3), None)
    assert [s["service"] for s in spend.by_service] == ["Virtual Machines", "Azure Database for PostgreSQL", "Virtual Network"]
    assert spend.by_service[0]["cost"] == 150.13
    assert spend.total == 190.13
    assert [d["date"] for d in spend.daily] == ["2026-10-01", "2026-10-02", "2026-10-03"]
    # the unposted day (0.00) is left out of the average: (12 + 8) / 2 * 31 days
    assert spend.forecast == 310.0
    assert (spend.currency, spend.month, spend.budget) == ("USD", "2026-10", None)


def test_when_azure_has_posted_nothing_nothing_is_invented():
    empty = {"properties": {"columns": [{"name": "Cost"}, {"name": "ServiceName"}], "rows": []}}
    spend = az.parse(empty, {"properties": {"columns": [], "rows": []}}, date(2026, 10, 1), None)
    assert (spend.total, spend.forecast, spend.by_service, spend.daily) == (0.0, None, [], [])


async def test_not_configured_says_so_and_calls_nothing():
    azure = Azure()
    spend = await az.get_spend({}, get=azure.get, post=azure.post)
    assert spend.configured is False and azure.calls == []


async def test_a_read_signs_in_with_the_vm_identity_and_asks_read_only_questions():
    azure = Azure()
    spend = await az.get_spend({**ENV, "ACORN_AZURE_SPEND_BUDGET": "500"}, get=azure.get, post=azure.post, today=lambda: date(2026, 10, 3))
    assert spend.total == 190.13 and spend.budget == 500.0 and spend.error is None and spend.fetched_at
    kind, url, headers = azure.calls[0]
    assert kind == "get" and "169.254.169.254" in url and headers == {"Metadata": "true"}
    assert azure.calls[1][1].startswith("https://management.azure.com" + SCOPE + "/providers/Microsoft.CostManagement/query")
    assert azure.calls[1][2] == {"Authorization": "Bearer tok"}
    assert [b["type"] for b in azure.bodies] == ["ActualCost", "ActualCost"] and all(b["timeframe"] == "MonthToDate" for b in azure.bodies)


async def test_the_answer_is_kept_and_a_manual_refresh_is_limited():
    azure = Azure(cost=[Reply(200, BY_SERVICE), Reply(200, DAILY), Reply(200, BY_SERVICE), Reply(200, DAILY)])
    clock = [1000.0]
    kwargs = {"get": azure.get, "post": azure.post, "now": lambda: clock[0], "today": lambda: date(2026, 10, 3)}
    await az.get_spend(ENV, **kwargs)
    clock[0] += 60
    await az.get_spend(ENV, **kwargs)
    assert len(azure.bodies) == 2, "inside the cache time nothing is asked again"
    await az.get_spend(ENV, refresh=True, **kwargs)
    assert len(azure.bodies) == 2, "a refresh a minute after the last read is refused quietly"
    clock[0] += az.MIN_REFRESH_SECONDS
    await az.get_spend(ENV, refresh=True, **kwargs)
    assert len(azure.bodies) == 4
    clock[0] += az.CACHE_SECONDS + 1
    await az.get_spend(ENV, **kwargs)
    assert len(azure.bodies) == 6, "after the cache time it reads again"


@pytest.mark.parametrize(
    ("reply", "fragment"),
    [(Reply(403), "Cost Management Reader"), (Reply(429), "rate-limiting"), (Reply(500), "HTTP 500")],
)
async def test_azure_refusing_gives_a_reason_the_person_can_act_on(reply, fragment):
    azure = Azure(cost=[reply])
    spend = await az.get_spend(ENV, get=azure.get, post=azure.post)
    assert spend.configured is True and fragment in (spend.error or "") and spend.total == 0.0


async def test_no_identity_is_explained():
    azure = Azure(token=Reply(400))
    spend = await az.get_spend(ENV, get=azure.get, post=azure.post)
    assert "managed identity" in (spend.error or "") and azure.bodies == []


async def test_when_a_refresh_fails_the_last_good_answer_is_served_and_marked_stale():
    azure = Azure(cost=[Reply(200, BY_SERVICE), Reply(200, DAILY), Reply(429)])
    clock = [1000.0]
    kwargs = {"get": azure.get, "post": azure.post, "now": lambda: clock[0], "today": lambda: date(2026, 10, 3)}
    good = await az.get_spend(ENV, **kwargs)
    clock[0] += az.CACHE_SECONDS + 1
    later = await az.get_spend(ENV, **kwargs)
    assert later.stale is True and "rate-limiting" in (later.error or "")
    assert later.total == good.total and later.fetched_at == good.fetched_at

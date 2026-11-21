"""With several API processes the health page merges what every process published about its background workers."""

import asyncio
import json

from app.services import worker_heartbeat as wh


def row(name, since, status="ok", recent=None):
    return {"name": name, "interval_seconds": 60, "seconds_since_pass": since, "passes": 3, "last_error": None, "status": status, "recent": recent or [], "recent_failed": 0}


def test_the_process_that_ran_the_worker_wins_over_one_that_only_knows_it_is_waiting():
    runner = (1000.0, [row("alert_suppression", 20), row("dmarc", 5)])
    idle = (1000.0, [row("alert_suppression", None, "waiting")])
    merged = wh.merge_published([idle, runner], now_epoch=1000.0)
    assert [(r["name"], r["status"], r["seconds_since_pass"]) for r in merged] == [("alert_suppression", "ok", 20), ("dmarc", "ok", 5)]


def test_ages_move_on_by_how_long_ago_the_report_was_made_and_the_freshest_pass_wins():
    old = (1000.0, [row("w", 100, recent=[{"seconds_ago": 100, "ok": True, "error": None}])])
    new = (1010.0, [row("w", 3)])
    merged = wh.merge_published([old, new], now_epoch=1020.0)
    assert merged[0]["seconds_since_pass"] == 13  # 3 seconds at the time + 10 since it was published
    only_old = wh.merge_published([old], now_epoch=1040.0)
    assert only_old[0]["seconds_since_pass"] == 140 and only_old[0]["recent"][0]["seconds_ago"] == 140


def test_a_process_that_stopped_publishing_is_ignored_and_the_worst_status_is_listed_first():
    gone = (0.0, [row("dead", 1)])
    live = (1000.0, [row("fine", 1, "ok"), row("broken", 400, "late"), row("sick", 5, "failing")])
    merged = wh.merge_published([gone, live], now_epoch=1000.0 + 5)
    assert [r["name"] for r in merged] == ["broken", "sick", "fine"]


class FakeRedis:
    def __init__(self):
        self.data = {}

    async def set(self, key, value, ex=None):
        self.data[key] = value

    async def get(self, key):
        return self.data.get(key)

    async def scan_iter(self, match=None):
        prefix = (match or "").rstrip("*")
        for k in list(self.data):
            if k.startswith(prefix):
                yield k


def test_a_process_publishes_its_snapshot_and_another_reads_the_merged_view_and_a_broken_redis_falls_back_to_its_own():
    async def go():
        wh.reset()
        wh.expect("alert_suppression", 60, 0, now=0)
        wh.beat("alert_suppression", now=0)
        r = FakeRedis()
        await wh.publish_once(r, 111)
        assert json.loads(r.data[f"{wh._KEY}111"])["rows"][0]["name"] == "alert_suppression"
        other_process_view = await wh.shared_snapshot(r)
        assert [x["name"] for x in other_process_view] == ["alert_suppression"]

        class Broken:
            def scan_iter(self, match=None):
                raise OSError("redis is down")

        wh.reset()
        wh.expect("own", 60, 0)
        assert [x["name"] for x in await wh.shared_snapshot(Broken())] == ["own"]
        wh.reset()

    asyncio.run(go())

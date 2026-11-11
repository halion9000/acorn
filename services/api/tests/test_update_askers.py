"""Who asked for each update run: the API notes each request, and the history list puts a run down to the request that came just before it."""

from datetime import UTC, datetime, timedelta

from app.services import update_control as uc

T0 = datetime(2026, 11, 11, 12, 0, 0, tzinfo=UTC)


def row(at: datetime, seconds: int | None = 240, mode: str = "update") -> dict:
    return {"at": at.strftime("%Y-%m-%dT%H:%M:%SZ"), "status": "ok", "ok": True, "commit": "aaa1111", "mode": mode, "seconds": seconds}


def test_a_request_is_noted_with_who_and_when_and_only_the_latest_fifty_are_kept(tmp_path):
    uc.request_update(tmp_path, "hal@example.com", now=T0)
    assert uc.read_asked(tmp_path) == [(T0, "hal@example.com")]
    (tmp_path / uc.REQUEST_FILE).unlink()
    for i in range(60):
        uc.request_update(tmp_path, f"p{i}@example.com", now=T0 + timedelta(minutes=i + 1))
        (tmp_path / uc.REQUEST_FILE).unlink()
    asked = uc.read_asked(tmp_path)
    assert len(asked) == uc.ASKED_KEPT and asked[-1][1] == "p59@example.com" and asked[0][1] == "p10@example.com"


def test_a_note_that_cannot_be_read_is_skipped_and_no_file_is_nobody(tmp_path):
    assert uc.read_asked(tmp_path) == []
    (tmp_path / uc.ASKED_FILE).write_text(
        'not json\n{"by": "", "at": "2026-11-11T12:00:00+00:00"}\n{"by": "a@x.test"}\n{"by": "ok@x.test", "at": "2026-11-11T12:00:00+00:00"}\n'
    )
    assert uc.read_asked(tmp_path) == [(T0, "ok@x.test")]


def test_a_run_is_put_down_to_the_request_just_before_it_and_a_run_nobody_asked_for_has_no_name():
    asked = [(T0, "hal@example.com"), (T0 + timedelta(hours=3), "ann@example.com")]
    rows = [
        row(T0 + timedelta(hours=3, minutes=5)),  # ann's
        row(T0 + timedelta(hours=1)),  # started on the server: no request near it
        row(T0 + timedelta(minutes=5)),  # hal's
    ]
    out = uc.attach_askers(rows, asked)
    assert [r["asked_by"] for r in out] == ["ann@example.com", None, "hal@example.com"]
    assert [r["at"] for r in out] == [r["at"] for r in rows], "the order and the other fields are kept"


def test_one_request_names_one_run_only_and_a_long_run_still_finds_its_request():
    asked = [(T0, "hal@example.com")]
    two = uc.attach_askers([row(T0 + timedelta(minutes=10)), row(T0 + timedelta(minutes=4))], asked)
    assert [r["asked_by"] for r in two] == [None, "hal@example.com"], "the first run recorded after the request takes it"
    long_run = uc.attach_askers([row(T0 + timedelta(minutes=50), seconds=25 * 60)], asked)
    assert long_run[0]["asked_by"] == "hal@example.com", "30 minutes plus the run's own 25"
    too_late = uc.attach_askers([row(T0 + timedelta(minutes=50), seconds=60)], asked)
    assert too_late[0]["asked_by"] is None
    before = uc.attach_askers([row(T0 - timedelta(minutes=1))], asked)
    assert before[0]["asked_by"] is None, "a request made after the run is not its cause"


def test_the_state_the_page_reads_carries_who_asked(tmp_path):
    uc.request_update(tmp_path, "hal@example.com", now=T0)
    (tmp_path / uc.REQUEST_FILE).unlink()
    done = (T0 + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / uc.HISTORY_FILE).write_text("\t".join([done, "ok", "aaa1111", "update", "245"]) + "\n")
    history = uc.read_state(tmp_path).history
    assert history[0]["asked_by"] == "hal@example.com" and history[0]["seconds"] == 245

"""The Update button's hand-off: what a request writes, what is read back, and who may ask."""

import json
from datetime import UTC, datetime

import pytest
from app.services import update_control as uc


def test_control_dir_comes_only_from_the_setting():
    assert uc.control_dir({}) is None
    assert uc.control_dir({"ACORN_UPDATE_CTL_DIR": "  "}) is None
    assert str(uc.control_dir({"ACORN_UPDATE_CTL_DIR": "/update-ctl"})).replace("\\", "/") == "/update-ctl"


def test_without_the_folder_nothing_is_offered_and_a_request_is_refused(tmp_path):
    assert uc.read_state(None).available is False
    assert uc.read_state(tmp_path / "missing").state == "unavailable"
    with pytest.raises(uc.UpdateRefused) as refused:
        uc.request_update(tmp_path / "missing", "a@x.example")
    assert refused.value.code == "unavailable"


def test_a_request_is_a_small_file_with_no_command_and_a_second_is_refused_until_it_is_taken(tmp_path):
    uc.request_update(tmp_path, "hal@x.example", now=datetime(2026, 10, 31, 12, 0, tzinfo=UTC))
    body = json.loads((tmp_path / uc.REQUEST_FILE).read_text())
    assert body == {"requested_by": "hal@x.example", "requested_at": "2026-10-31T12:00:00+00:00"}
    state = uc.read_state(tmp_path)
    assert (state.state, state.requested_by) == ("queued", "hal@x.example")
    with pytest.raises(uc.UpdateRefused) as refused:
        uc.request_update(tmp_path, "other@x.example")
    assert refused.value.code == "busy"
    assert not list(tmp_path.glob("*.tmp")), "no half-written file is left behind"
    (tmp_path / uc.REQUEST_FILE).unlink()
    (tmp_path / uc.RUNNING_FILE).write_text("")
    assert uc.read_state(tmp_path).state == "running"
    with pytest.raises(uc.UpdateRefused):
        uc.request_update(tmp_path, "other@x.example")


@pytest.mark.parametrize(
    ("lines", "ok"),
    [
        (["[10:00:00] updating a -> b", "[10:04:00] UPDATE OK (b)"], True),
        (["[10:00:00] already up to date at b"], True),
        (["[10:04:00] UPDATE FAILED at b", "[10:06:00] ROLLED BACK to a: A.C.O.R.N is running the old version again"], False),
        (["[10:00:00] FAILED: could not fetch from GitHub"], False),
        (["[10:00:00] building..."], None),
    ],
)
def test_the_last_run_is_judged_from_the_script_output(tmp_path, lines, ok):
    (tmp_path / uc.RUN_LOG).write_text("\n".join(lines) + "\n")
    state = uc.read_state(tmp_path)
    assert state.state == "idle"
    assert state.last_run_ok is ok
    assert state.log == lines and state.last_run_at


def test_while_running_the_log_is_shown_without_a_verdict_and_only_the_tail_is_kept(tmp_path):
    (tmp_path / uc.RUNNING_FILE).write_text("")
    (tmp_path / uc.RUN_LOG).write_text("\n".join(f"line {i}" for i in range(100)) + "\n")
    state = uc.read_state(tmp_path)
    assert state.last_run_ok is None and state.summary == "line 99"
    assert state.log[0] == "line 60" and len(state.log) == uc.TAIL_LINES


def _bash():
    import shutil

    return shutil.which("bash")


@pytest.mark.skipif(_bash() is None, reason="needs bash")
def test_the_vm_runner_takes_the_request_runs_the_script_once_and_the_screen_reads_the_result(tmp_path):
    import subprocess
    from pathlib import Path

    runner = Path(__file__).resolve().parents[3] / "infra" / "azure" / "acorn-update-runner.sh"
    ctl = tmp_path / "ctl"
    ctl.mkdir()
    script = tmp_path / "fake-update.sh"
    script.write_text("echo '[10:00:00] fetching main...'\necho '[10:04:00] UPDATE OK (abc1234)'\n")
    env = {"PATH": __import__("os").environ["PATH"], "ACORN_UPDATE_CTL": ctl.as_posix(), "ACORN_UPDATE_SCRIPT": script.as_posix()}

    def run():
        return subprocess.run([_bash(), runner.as_posix()], env=env, capture_output=True, text=True, timeout=60)

    assert run().returncode == 0 and not (ctl / uc.RUN_LOG).exists(), "no request: nothing runs"
    uc.request_update(ctl, "hal@x.example")
    assert run().returncode == 0
    state = uc.read_state(ctl)
    assert state.state == "idle" and state.last_run_ok is True
    assert any("UPDATE OK (abc1234)" in line for line in state.log)
    assert not (ctl / uc.REQUEST_FILE).exists() and not (ctl / uc.RUNNING_FILE).exists()
    # a failing script is reported as a failure
    script.write_text("echo '[10:00:00] FAILED: could not fetch from GitHub'\nexit 1\n")
    uc.request_update(ctl, "hal@x.example")
    run()
    after = uc.read_state(ctl)
    assert after.last_run_ok is False
    # a run that is already in progress is not started a second time
    (ctl / uc.RUNNING_FILE).write_text("")
    (ctl / uc.REQUEST_FILE).write_text("{}")
    before = (ctl / uc.RUN_LOG).read_text()
    run()
    assert (ctl / uc.RUN_LOG).read_text() == before


TAB = chr(9)


def _line(*fields):
    return TAB.join(fields)


def test_history_is_read_newest_first_with_ok_only_for_the_statuses_that_mean_it_worked(tmp_path):
    (tmp_path / uc.HISTORY_FILE).write_text(
        "\n".join(
            [
                _line("2026-11-09T10:00:00Z", "ok", "aaa1111", "update"),
                _line("2026-11-09T11:00:00Z", "rolled_back", "aaa1111", "update"),
                _line("2026-11-10T09:00:00Z", "failed", "none", "update"),
                _line("2026-11-10T12:00:00Z", "rollback_ok", "aaa1111", "rollback"),
            ]
        )
        + "\n"
    )
    history = uc.read_state(tmp_path).history
    assert [h["at"] for h in history] == ["2026-11-10T12:00:00Z", "2026-11-10T09:00:00Z", "2026-11-09T11:00:00Z", "2026-11-09T10:00:00Z"]
    assert [h["ok"] for h in history] == [True, False, False, True]
    assert history[1]["commit"] is None and history[0] == {
        "at": "2026-11-10T12:00:00Z",
        "status": "rollback_ok",
        "ok": True,
        "commit": "aaa1111",
        "mode": "rollback",
        "seconds": None,
    }


def test_a_line_that_is_not_four_plain_fields_is_skipped_and_only_the_newest_twenty_are_shown():
    good = _line("2026-11-10T12:00:00Z", "ok", "aaa1111", "update")
    text = "\n".join(
        [
            "",
            "garbage",
            _line("2026-11-10T12:00:00Z", "ok", "aaa1111"),
            _line("not-a-time", "ok", "aaa1111", "update"),
            _line("2026-11-10T12:00:00Z", "<script>alert(1)</script>", "aaa1111", "update"),
            _line("2026-11-10T12:00:00Z", "ok", "aaa1111", "update", "extra"),
            good,
        ]
    )
    assert uc.parse_history(text) == [
        {"at": "2026-11-10T12:00:00Z", "status": "ok", "ok": True, "commit": "aaa1111", "mode": "update", "seconds": None}
    ]
    many = "\n".join(_line(f"2026-11-{d:02d}T12:00:00Z", "ok", "aaa1111", "update") for d in range(1, 29))
    shown = uc.parse_history(many)
    assert len(shown) == uc.HISTORY_SHOWN and shown[0]["at"] == "2026-11-28T12:00:00Z"


def test_no_history_file_is_an_empty_history_not_an_error(tmp_path):
    assert uc.read_state(tmp_path).history == []


def test_a_line_with_the_seconds_the_run_took_shows_them_and_a_fifth_field_that_is_not_a_number_is_skipped():
    rows = uc.parse_history(
        "\n".join(
            [
                _line("2026-11-10T12:00:00Z", "ok", "aaa1111", "update", "245"),
                _line("2026-11-10T12:05:00Z", "ok", "aaa1111", "update", "-5"),
                _line("2026-11-10T12:06:00Z", "ok", "aaa1111", "update", "1e3"),
                _line("2026-11-10T12:07:00Z", "failed", "none", "verify", "0"),
            ]
        )
    )
    assert [(r["at"], r["seconds"]) for r in rows] == [("2026-11-10T12:07:00Z", 0), ("2026-11-10T12:00:00Z", 245)]

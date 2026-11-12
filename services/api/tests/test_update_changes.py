"""What each update brought: the update script's own function writes the commit titles (run for real, in bash, against a real git repository), and the API reads them back safely."""

import shutil
import subprocess
from pathlib import Path

import pytest
from app.services import update_control as uc

SCRIPT = Path(__file__).resolve().parents[3] / "infra" / "azure" / "update-acorn.sh"
BASH = shutil.which("bash")
GIT = shutil.which("git")
needs_tools = pytest.mark.skipif(BASH is None or GIT is None, reason="needs bash and git")


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        [GIT, "-C", str(repo), "-c", "user.name=test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false", *args],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return out.stdout.strip()


def commit(repo: Path, title: str) -> None:
    (repo / "file.txt").write_text(title)
    git(repo, "add", "file.txt")
    git(repo, "commit", "-q", "-m", title)


def run_record_changes(repo: Path, ctl: Path, before: str, target: str) -> str:
    """The script's own function, run in bash with the folder it writes to pointed at a temporary one."""
    program = (
        f"REPO={repo.as_posix()}\nexport ACORN_UPDATE_CTL={ctl.as_posix()}\n"
        f"eval \"$(sed -n '/^record_changes() {{/,/^}}/p' {SCRIPT.as_posix()})\"\n"
        f'record_changes "{before}" "{target}"; echo "exit=$?"\n'
    )
    return subprocess.run([BASH, "-c", program], capture_output=True, text=True, timeout=60).stdout


@pytest.fixture
def repo(tmp_path):
    folder = tmp_path / "repo"
    folder.mkdir()
    git(folder, "init", "-q")
    commit(folder, "First thing")
    before = git(folder, "rev-parse", "--short", "HEAD")
    commit(folder, "Second thing")
    commit(folder, "Third thing: with a colon")
    git(folder, "fetch", "-q", ".", "HEAD")  # leaves FETCH_HEAD at the newest commit, as the update's own fetch does
    target = git(folder, "rev-parse", "--short", "FETCH_HEAD")
    ctl = tmp_path / "ctl"
    ctl.mkdir()
    return folder, ctl, before, target


@needs_tools
def test_the_script_writes_the_titles_between_the_old_and_new_version_and_the_api_reads_them(repo):
    folder, ctl, before, target = repo
    assert "exit=0" in run_record_changes(folder, ctl, before, target)
    assert uc.read_changes(ctl, target) == [
        "Third thing: with a colon",
        "Second thing",
    ], "newest first, and not the commit that was already running"


@needs_tools
def test_it_never_fails_a_run_with_no_folder_an_unknown_old_version_or_an_odd_target(repo, tmp_path):
    folder, ctl, before, target = repo
    assert "exit=0" in run_record_changes(folder, tmp_path / "missing", before, target)
    assert not (tmp_path / "missing").exists(), "it never creates the hand-off folder itself"
    assert "exit=0" in run_record_changes(folder, ctl, "none", target)
    assert uc.read_changes(ctl, target) == [], "an unknown old version lists nothing rather than everything"
    assert "exit=0" in run_record_changes(folder, ctl, before, "../escape")
    assert (
        not (ctl / "escape.txt").exists() and not (ctl.parent / "escape.txt").exists()
    ), "a target that is not a plain hash writes nothing"


@needs_tools
def test_only_the_latest_fifty_files_are_kept(repo):
    folder, ctl, before, target = repo
    (ctl / "changes").mkdir()
    for i in range(60):
        (ctl / "changes" / f"{i:07x}.txt").write_text("old")
    assert "exit=0" in run_record_changes(folder, ctl, before, target)
    kept = sorted(p.name for p in (ctl / "changes").iterdir())
    assert len(kept) == 50 and f"{target}.txt" in kept


def test_titles_are_read_as_plain_text_capped_in_number_and_length(tmp_path):
    (tmp_path / "changes").mkdir()
    lines = ["  Fix the thing  ", "", "bell\x07 and escape\x1b[31m gone", "x" * 500] + [f"change {i}" for i in range(40)]
    (tmp_path / "changes" / "abc1234.txt").write_text("\n".join(lines), encoding="utf-8")
    out = uc.read_changes(tmp_path, "abc1234")
    assert out[0] == "Fix the thing"
    assert out[1] == "bell and escape[31m gone", "control characters are dropped; the text stays one plain line"
    assert out[2] == "x" * uc.CHANGE_MAX
    assert len(out) == uc.CHANGES_SHOWN


def test_a_commit_that_is_not_a_plain_hash_or_has_no_file_reads_nothing(tmp_path):
    (tmp_path / "changes").mkdir()
    (tmp_path / "secret.txt").write_text("do not read me")
    for bad in ("../secret", "..\\secret", "abc", "ABC1234", "abc1234.txt", "", None):
        assert uc.read_changes(tmp_path, bad) == []
    assert uc.read_changes(tmp_path, "abc1234") == [], "no file for this commit"
    assert uc.read_changes(tmp_path / "nowhere", "abc1234") == []


def test_only_a_run_that_updated_and_passed_lists_what_it_brought(tmp_path):
    (tmp_path / "changes").mkdir()
    (tmp_path / "changes" / "abc1234.txt").write_text("Add the label\n")
    rows = [
        {"status": "ok", "commit": "abc1234"},
        {"status": "rolled_back", "commit": "abc1234"},
        {"status": "verify_ok", "commit": "abc1234"},
        {"status": "ok", "commit": None},
    ]
    out = uc.attach_changes(rows, tmp_path)
    assert [r["changes"] for r in out] == [["Add the label"], [], [], []]


def test_the_state_the_page_reads_carries_the_changes_on_its_history_rows(tmp_path):
    (tmp_path / "changes").mkdir()
    (tmp_path / "changes" / "abc1234.txt").write_text("Add the label\nFix the digest\n")
    (tmp_path / uc.HISTORY_FILE).write_text("2026-11-11T10:00:00Z\tok\tabc1234\tupdate\t245\n")
    state = uc.read_state(tmp_path)
    assert state.history[0]["commit"] == "abc1234"
    assert state.history[0]["changes"] == ["Add the label", "Fix the digest"]

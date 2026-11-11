"""The update script's helper that gives the intake service its own database connection (run for real, in bash, against sample .env files)."""

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "infra" / "azure" / "update-acorn.sh"
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")


def run_helper(tmp_path: Path, env_text: str):
    (tmp_path / ".env").write_text(env_text)
    program = (
        f'say() {{ echo "$*"; }}\nREPO={tmp_path.as_posix()}\n'
        f"eval \"$(sed -n '/^ensure_ingest_dsn() {{/,/^}}/p' {SCRIPT.as_posix()})\"\n"
        'ensure_ingest_dsn; echo "exit=$?"\n'
    )
    out = subprocess.run([BASH, "-c", program], capture_output=True, text=True, timeout=60)
    return out.stdout, (tmp_path / ".env").read_text()


def test_it_derives_the_connection_from_the_migration_url_and_keeps_the_other_lines(tmp_path):
    said, env = run_helper(
        tmp_path, "ONE=1\nAZURE_MIGRATION_DATABASE_URL=postgresql+asyncpg://admin:p%40ss@db.example:5432/aisoc?ssl=require\nTWO=2\n"
    )
    assert "exit=0" in said and "added AZURE_INGEST_DSN" in said
    lines = env.splitlines()
    assert "ONE=1" in lines and "TWO=2" in lines and lines[1].startswith("AZURE_MIGRATION_DATABASE_URL=")
    assert "AZURE_INGEST_DSN=postgres://admin:p%40ss@db.example:5432/aisoc?sslmode=require" in lines


def test_a_last_line_without_a_newline_is_not_swallowed(tmp_path):
    _, env = run_helper(tmp_path, "AZURE_MIGRATION_DATABASE_URL=postgresql+asyncpg://a:b@h:5432/aisoc?ssl=require")
    lines = env.splitlines()
    assert lines[0] == "AZURE_MIGRATION_DATABASE_URL=postgresql+asyncpg://a:b@h:5432/aisoc?ssl=require", "the URL line is intact"
    assert lines[1] == "AZURE_INGEST_DSN=postgres://a:b@h:5432/aisoc?sslmode=require"


def test_it_is_a_no_op_when_the_setting_is_already_there_and_says_why_when_there_is_nothing_to_derive_from(tmp_path):
    said, env = run_helper(tmp_path, "AZURE_INGEST_DSN=postgres://x:y@z/aisoc?sslmode=require\n")
    assert "exit=0" in said and "added" not in said and env.count("AZURE_INGEST_DSN=") == 1
    said, env = run_helper(tmp_path / "second" if (tmp_path / "second").mkdir() is None else tmp_path, "ONE=1\n")
    assert "exit=1" in said and "FAILED: AZURE_MIGRATION_DATABASE_URL is not in" in said
    assert "AZURE_INGEST_DSN" not in env


def test_the_compose_file_hands_that_setting_to_the_intake_service_exactly_once():
    compose = (SCRIPT.parent / "docker-compose.azure.yml").read_text()
    assert compose.count("DATABASE_DSN: ${AZURE_INGEST_DSN:?set AZURE_INGEST_DSN}") == 1
    services = [
        line
        for line in compose.splitlines()
        if line.startswith("  ") and not line.startswith("   ") and line.rstrip().endswith(":") and not line.strip().startswith("#")
    ]
    assert len(services) == len(set(services)), "no service is defined twice (that stopped an update on 2026-10-31)"


def run_plain(tmp_path: Path, env_text: str):
    (tmp_path / ".env").write_text(env_text)
    program = (
        f'say() {{ echo "$*"; }}\nREPO={tmp_path.as_posix()}\n'
        f"eval \"$(sed -n '/^ensure_plain_database_url() {{/,/^}}/p' {SCRIPT.as_posix()})\"\n"
        'ensure_plain_database_url; echo "exit=$?"\n'
    )
    out = subprocess.run([BASH, "-c", program], capture_output=True, text=True, timeout=60)
    return out.stdout, (tmp_path / ".env").read_text()


def test_the_ssl_setting_is_removed_from_the_app_database_address_and_nothing_else_is_touched(tmp_path):
    original = (
        "ONE=1\nAZURE_DATABASE_URL=postgresql+asyncpg://aisoc_app:p%40ss@db.example:5432/aisoc?ssl=require\n"
        "AZURE_MIGRATION_DATABASE_URL=postgresql+asyncpg://admin:pw@db.example:5432/aisoc?ssl=require\nTWO=2\n"
    )
    said, env = run_plain(tmp_path, original)
    assert "exit=0" in said and "removed ?ssl=" in said
    lines = env.splitlines()
    assert "AZURE_DATABASE_URL=postgresql+asyncpg://aisoc_app:p%40ss@db.example:5432/aisoc" in lines
    assert (
        "AZURE_MIGRATION_DATABASE_URL=postgresql+asyncpg://admin:pw@db.example:5432/aisoc?ssl=require" in lines
    ), "the migration address keeps it: its own tool reads it"
    assert "ONE=1" in lines and "TWO=2" in lines


def test_other_settings_on_the_address_stay_and_an_address_without_ssl_is_left_alone(tmp_path):
    _, env = run_plain(tmp_path, "AZURE_DATABASE_URL=postgresql+asyncpg://u:p@h:5432/aisoc?ssl=require&application_name=acorn\n")
    assert env.strip() == "AZURE_DATABASE_URL=postgresql+asyncpg://u:p@h:5432/aisoc?application_name=acorn"
    said, env = run_plain(
        tmp_path / "x" if (tmp_path / "x").mkdir() is None else tmp_path, "AZURE_DATABASE_URL=postgresql+asyncpg://u:p@h:5432/aisoc\n"
    )
    assert "removed" not in said and env.strip() == "AZURE_DATABASE_URL=postgresql+asyncpg://u:p@h:5432/aisoc"


def test_every_service_that_gets_the_database_address_also_gets_ssl_required_through_pgsslmode():
    compose = (SCRIPT.parent / "docker-compose.azure.yml").read_text()
    with_url = compose.count("DATABASE_URL: ${AZURE_DATABASE_URL:?set AZURE_DATABASE_URL}")
    assert with_url >= 9
    assert compose.count("PGSSLMODE: require") == with_url, "one PGSSLMODE for each service that gets the address"


# The statuses the script's last line can carry. CORE (hud/src/aisoc-remote-deploy.test.ts) keeps the same list and reads exactly these: change both together.
RESULT_STATUSES = ["ok", "up_to_date", "verify_ok", "rollback_ok", "rolled_back", "failed", "verify_failed", "rollback_failed", "busy"]


def run_copy_of_script(tmp_path: Path, *args: str):
    """The real script, with its two fixed folders pointed at temporary ones and the checkout folder missing."""
    text = (
        SCRIPT.read_text()
        .replace("REPO=/srv/acorn/AiSOC", f"REPO={(tmp_path / 'no-checkout').as_posix()}")
        .replace("STATE=/srv/acorn", f"STATE={tmp_path.as_posix()}")
    )
    copy = tmp_path / "update-acorn.sh"
    copy.write_text(text)
    return subprocess.run([BASH, str(copy), *args], capture_output=True, text=True, timeout=60)


def test_every_status_comes_out_as_one_json_line_with_the_status_and_a_commit(tmp_path):
    import json

    for status in RESULT_STATUSES:
        program = (
            f"REPO={tmp_path.as_posix()}\nSTATUS={status}\n"
            f"eval \"$(sed -n '/^emit_result() {{/p' {SCRIPT.as_posix()})\"\n"
            "emit_result\n"
        )
        out = subprocess.run([BASH, "-c", program], capture_output=True, text=True, timeout=60).stdout.strip()
        assert out.startswith("RESULT "), out
        body = json.loads(out[len("RESULT ") :])
        assert body == {"status": status, "commit": "none"}


@pytest.mark.skipif(shutil.which("flock") is None, reason="needs flock")
def test_a_real_run_that_fails_early_still_ends_with_a_failed_result_line(tmp_path):
    out = run_copy_of_script(tmp_path).stdout.strip().splitlines()
    assert any("FAILED:" in line and "does not exist" in line for line in out)
    assert out[-1] == 'RESULT {"status":"failed","commit":"none"}'


@pytest.mark.skipif(shutil.which("flock") is None, reason="needs flock")
def test_a_second_run_while_one_holds_the_lock_ends_with_busy(tmp_path):
    holder = subprocess.Popen(
        [BASH, "-c", f"exec 9>{(tmp_path / 'update.lock').as_posix()}; flock -n 9; echo held; sleep 20"], stdout=subprocess.PIPE, text=True
    )
    try:
        assert holder.stdout.readline().strip() == "held"
        result = run_copy_of_script(tmp_path)
        assert result.stdout.strip().splitlines()[-1] == 'RESULT {"status":"busy","commit":"none"}'
        assert result.returncode == 3
    finally:
        holder.kill()


def test_the_azure_honeytoken_service_gets_a_public_canary_address_not_localhost():
    import yaml

    class Loader(yaml.SafeLoader):
        pass

    # docker compose's merge tags (!override, !reset) mean nothing to a plain reader: take the value as it is.
    Loader.add_multi_constructor(
        "!",
        lambda loader, suffix, node: loader.construct_sequence(node)
        if isinstance(node, yaml.SequenceNode)
        else loader.construct_mapping(node)
        if isinstance(node, yaml.MappingNode)
        else loader.construct_scalar(node),
    )
    compose = yaml.load((SCRIPT.parent / "docker-compose.azure.yml").read_text(), Loader=Loader)  # noqa: S506 - SafeLoader subclass
    value = compose["services"]["honeytokens"]["environment"]["HONEYTOKEN_CANARY_BASE_URL"]
    # The public tripwire address (ACORN_CANARY_URL) wins when it is set; otherwise the console address, never localhost.
    assert value == "${ACORN_CANARY_URL:-${ACORN_PUBLIC_URL:-https://acorn.goliveoak.com}}"
    assert "localhost" not in value


def test_the_settings_the_health_page_reads_actually_reach_the_api_container():
    import yaml

    class Loader(yaml.SafeLoader):
        pass

    Loader.add_multi_constructor(
        "!",
        lambda loader, suffix, node: loader.construct_sequence(node)
        if isinstance(node, yaml.SequenceNode)
        else loader.construct_mapping(node)
        if isinstance(node, yaml.MappingNode)
        else loader.construct_scalar(node),
    )
    base = yaml.load((SCRIPT.parents[2] / "docker-compose.yml").read_text(), Loader=Loader)  # noqa: S506 - SafeLoader subclass
    env = base["services"]["api"]["environment"]
    assert env["MICROSOFT_CLIENT_SECRET_EXPIRES"] == "${MICROSOFT_CLIENT_SECRET_EXPIRES:-}"
    assert env["RETENTION_ALERTS_KEEP_FOREVER_OK"] == "${RETENTION_ALERTS_KEEP_FOREVER_OK:-false}"
    # the container only receives what is listed here: the DMARC mailbox reader needs these, or it silently does nothing
    for name in (
        "DMARC_MAILBOX",
        "DMARC_OWNER_TENANT_ID",
        "DMARC_GRAPH_TENANT_ID",
        "DMARC_GRAPH_CLIENT_ID",
        "DMARC_GRAPH_CLIENT_SECRET",
        "ALERT_EMAIL_GRAPH_TENANT_ID",
        "ALERT_EMAIL_GRAPH_CLIENT_ID",
        "ALERT_EMAIL_GRAPH_CLIENT_SECRET",
    ):
        assert env[name] == "${" + name + ":-}", name


CADDYFILE = SCRIPT.parent / "caddy" / "Caddyfile"


def _handles(text: str) -> dict[str, str]:
    """Each top-level `handle` block of the Caddyfile: its matcher (or '' for the catch-all) and the address it proxies to."""
    import re

    out: dict[str, str] = {}
    text = text.split("\n:8088 {")[0]  # the console's site only; the tripwire listener has its own test
    for m in re.finditer(r"^\thandle\s*(@\w+)?\s*\{(.*?)^\t\}", text, flags=re.S | re.M):
        target = re.search(r"reverse_proxy\s+(\S+)", m.group(2))
        out[m.group(1) or ""] = target.group(1) if target else ""
    return out


def test_the_live_feed_websocket_and_the_event_stream_go_straight_to_the_realtime_service_and_everything_else_to_the_web_container():
    import re

    text = CADDYFILE.read_text(encoding="utf-8")
    assert _handles(text) == {"@realtime": "realtime:4000", "": "web:3000"}
    matcher = re.search(r"^\t@realtime\s+path\s+(.+)$", text, flags=re.M)
    assert matcher is not None and set(matcher.group(1).split()) == {"/ws", "/ws/*", "/sse"}
    assert "flush_interval -1" in text, "the event stream must not be buffered"


def test_a_changed_proxy_file_is_loaded_when_an_update_runs_not_only_when_the_container_is_recreated():
    script = SCRIPT.read_text(encoding="utf-8")
    start = script.index("$COMPOSE up -d")
    assert (
        "caddy reload --config /etc/caddy/Caddyfile" in script[start : start + 900]
    ), "the proxy is not told to read its file again after the services start"


def test_a_failing_reload_never_fails_the_update():
    line = next(ln for ln in SCRIPT.read_text(encoding="utf-8").splitlines() if "caddy reload" in ln)
    assert line.rstrip().endswith("|| true"), line


def test_the_proxy_gets_its_whole_folder_so_a_changed_file_is_seen_by_the_running_container():
    compose = (SCRIPT.parent / "docker-compose.azure.yml").read_text(encoding="utf-8")
    assert "- ./infra/azure/caddy:/etc/caddy:ro" in compose
    assert "caddy/Caddyfile:/etc/caddy/Caddyfile" not in compose, "a single-file mount goes stale when git replaces the file"


def run_extras(tmp_path: Path, env_text: str | None):
    (tmp_path / "compose.log").unlink(missing_ok=True)  # each call starts with an empty record of what was run
    if env_text is not None:
        (tmp_path / ".env").write_text(env_text)
    program = (
        f'say() {{ echo "$*"; }}\nREPO={tmp_path.as_posix()}\n'
        f'COMPOSE() {{ echo "compose $*" >> {tmp_path.as_posix()}/compose.log; }}\n'
        f"eval \"$(sed -n '/^start_extras() {{/,/^}}/p' {SCRIPT.as_posix()} | sed 's/\\$COMPOSE /COMPOSE /g')\"\n"
        'start_extras; echo "exit=$?"\n'
    )
    out = subprocess.run([BASH, "-c", program], capture_output=True, text=True, timeout=60)
    log = tmp_path / "compose.log"
    return out.stdout + (log.read_text() if log.exists() else "")


def test_honeytokens_start_by_default_and_purple_team_does_not(tmp_path):
    said = run_extras(tmp_path, "OTHER=1\n")
    assert "compose --profile extras build honeytokens" in said and "compose --profile extras up -d honeytokens" in said
    assert "purple-team" not in said and "exit=0" in said


def test_the_owner_can_choose_which_extras_run_and_an_empty_list_turns_them_all_off(tmp_path):
    said = run_extras(tmp_path, 'ACORN_EXTRAS="honeytokens purple-team"\n')
    assert "up -d honeytokens purple-team" in said
    assert "compose" not in run_extras(tmp_path, "ACORN_EXTRAS=\n")


def test_a_setting_that_is_not_a_list_of_service_names_is_refused_not_run(tmp_path):
    said = run_extras(tmp_path, "ACORN_EXTRAS=honeytokens; rm -rf /\n")
    assert "left alone" in said and "compose" not in said


def test_the_extras_step_comes_after_the_services_start_and_never_fails_the_update():
    script = SCRIPT.read_text(encoding="utf-8")
    assert script.index("$COMPOSE up -d") < script.index("\n  start_extras\n") < script.index("migrate && healthy")
    body = script[script.index("start_extras() {") : script.index("deploy() {")]
    assert body.rstrip().endswith("}") and "return 0" in body.rsplit("}", 1)[0].splitlines()[-1] + "\n  return 0"


def test_the_running_version_is_the_commit_the_update_set_and_how_long_the_process_has_been_up(monkeypatch):
    from app.api.v1.endpoints import health

    monkeypatch.setenv("ACORN_COMMIT", " 97659064 ")
    v = health.running_version(now=health._STARTED_AT + 3725)
    assert v == {"commit": "97659064", "up_seconds": 3725}


def test_a_commit_that_was_never_set_is_none_not_a_made_up_value(monkeypatch):
    from app.api.v1.endpoints import health

    for value in (None, "", "   ", "unknown", "UNKNOWN"):
        if value is None:
            monkeypatch.delenv("ACORN_COMMIT", raising=False)
        else:
            monkeypatch.setenv("ACORN_COMMIT", value)
        assert health.running_version()["commit"] is None, value


def test_the_update_script_hands_the_commit_to_compose_and_compose_hands_it_to_the_api_container():
    script = SCRIPT.read_text(encoding="utf-8")
    deploy = script[script.index("deploy() {") :]
    assert deploy.index("ACORN_COMMIT=$(git") < deploy.index("export ACORN_COMMIT") < deploy.index("$COMPOSE build")
    import re

    compose = (SCRIPT.parents[2] / "docker-compose.yml").read_text(encoding="utf-8")
    at = compose.index("ACORN_COMMIT: ${ACORN_COMMIT:-}")
    owner = re.findall(r"^  ([a-z][a-z0-9-]*):\s*$", compose[:at], flags=re.M)[-1]
    assert owner == "api", f"the commit is handed to {owner}, not the API"
    assert compose.count("ACORN_COMMIT: ${ACORN_COMMIT:-}") == 1


def test_the_public_tripwire_listener_serves_only_the_canary_path_and_the_tunnel_token_is_never_in_git():
    import re

    import yaml

    text = CADDYFILE.read_text(encoding="utf-8")
    block = text[text.index("\n:8088 {") :]
    assert re.search(
        r"path_regexp\s+canary\s+\^/api/v1/canary/\[0-9a-fA-F-\]\{36\}\$", block
    ), "the tripwire matcher is no longer an exact id path"
    assert 'respond "Not found" 404' in block, "everything but the tripwire path must be a 404"
    assert "web:3000" not in block and "realtime:4000" not in block, "the public name must not reach the console or the realtime service"
    assert (
        "header_up X-Forwarded-For {http.request.header.Cf-Connecting-Ip}" in block
    ), "the visitor address must come from Cloudflare, not from the visitor"

    class Loader(yaml.SafeLoader):
        pass

    Loader.add_multi_constructor(
        "!",
        lambda loader, suffix, node: loader.construct_sequence(node)
        if isinstance(node, yaml.SequenceNode)
        else loader.construct_mapping(node)
        if isinstance(node, yaml.MappingNode)
        else loader.construct_scalar(node),
    )
    compose = yaml.load((SCRIPT.parent / "docker-compose.azure.yml").read_text(), Loader=Loader)  # noqa: S506 - SafeLoader subclass
    svc = compose["services"]["cloudflared"]
    assert svc["profiles"] == ["extras"], "the tunnel must not start unless the owner lists it"
    assert (
        svc["environment"]["TUNNEL_TOKEN"] == "${CLOUDFLARED_TUNNEL_TOKEN:-}"
    ), "the token must come from .env, never be written in the file"
    assert "ports" not in svc, "the tunnel connects out; nothing is published"


def run_record_history(tmp_path: Path, status: str, mode: str = "update", ctl: Path | None = None):
    """The script's own history function, run in bash with the folder it writes to pointed at a temporary one."""
    folder = ctl if ctl is not None else tmp_path
    program = (
        f"REPO={tmp_path.as_posix()}\nSTATUS={status}\nMODE={mode}\nexport ACORN_UPDATE_CTL={folder.as_posix()}\n"
        f"eval \"$(sed -n '/^record_history() {{/,/^}}/p' {SCRIPT.as_posix()})\"\n"
        'record_history; echo "exit=$?"\n'
    )
    return subprocess.run([BASH, "-c", program], capture_output=True, text=True, timeout=60).stdout


def test_a_run_that_did_something_adds_one_history_line_the_api_can_read(tmp_path):
    from app.services import update_control as uc

    assert "exit=0" in run_record_history(tmp_path, "ok")
    assert "exit=0" in run_record_history(tmp_path, "rolled_back")
    assert "exit=0" in run_record_history(tmp_path, "rollback_ok", mode="rollback")
    rows = uc.parse_history((tmp_path / "history.log").read_text())
    assert [(r["status"], r["mode"], r["ok"], r["commit"]) for r in rows] == [
        ("rollback_ok", "rollback", True, None),
        ("rolled_back", "update", False, None),
        ("ok", "update", True, None),
    ]


def test_a_run_that_was_turned_away_or_found_nothing_new_is_not_history(tmp_path):
    for status in ("busy", "up_to_date"):
        assert "exit=0" in run_record_history(tmp_path, status)
    assert not (tmp_path / "history.log").exists()


def test_history_never_fails_a_run_when_the_folder_is_missing_and_keeps_only_the_latest_fifty(tmp_path):
    assert "exit=0" in run_record_history(tmp_path, "ok", ctl=tmp_path / "missing")
    assert not (tmp_path / "missing").exists()
    (tmp_path / "history.log").write_text("".join(f"old-line-{i}\n" for i in range(60)))
    assert "exit=0" in run_record_history(tmp_path, "ok")
    lines = (tmp_path / "history.log").read_text().splitlines()
    assert len(lines) == 50 and lines[0] == "old-line-11" and lines[-1].split(chr(9))[1] == "ok"


@pytest.mark.skipif(shutil.which("flock") is None, reason="needs flock")
def test_a_real_failed_run_writes_history_and_the_result_line_is_still_last(tmp_path):
    import os

    from app.services import update_control as uc

    ctl = tmp_path / "ctl"
    ctl.mkdir()
    text = (
        SCRIPT.read_text()
        .replace("REPO=/srv/acorn/AiSOC", f"REPO={(tmp_path / 'no-checkout').as_posix()}")
        .replace("STATE=/srv/acorn", f"STATE={tmp_path.as_posix()}")
    )
    copy = tmp_path / "update-acorn.sh"
    copy.write_text(text)
    out = subprocess.run(
        [BASH, str(copy)], capture_output=True, text=True, timeout=60, env={**os.environ, "ACORN_UPDATE_CTL": ctl.as_posix()}
    )
    assert out.stdout.strip().splitlines()[-1] == 'RESULT {"status":"failed","commit":"none"}'
    rows = uc.parse_history((ctl / "history.log").read_text())
    assert [(r["status"], r["mode"]) for r in rows] == [("failed", "update")]

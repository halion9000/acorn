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
    assert value == "${ACORN_PUBLIC_URL:-https://acorn.goliveoak.com}"
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
    for name in ("DMARC_MAILBOX", "DMARC_OWNER_TENANT_ID", "DMARC_GRAPH_TENANT_ID", "DMARC_GRAPH_CLIENT_ID", "DMARC_GRAPH_CLIENT_SECRET", "ALERT_EMAIL_GRAPH_TENANT_ID", "ALERT_EMAIL_GRAPH_CLIENT_ID", "ALERT_EMAIL_GRAPH_CLIENT_SECRET"):
        assert env[name] == "${" + name + ":-}", name


CADDYFILE = SCRIPT.parent / "caddy" / "Caddyfile"


def _handles(text: str) -> dict[str, str]:
    """Each top-level `handle` block of the Caddyfile: its matcher (or '' for the catch-all) and the address it proxies to."""
    import re

    out: dict[str, str] = {}
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
    assert "caddy reload --config /etc/caddy/Caddyfile" in script[start : start + 900], "the proxy is not told to read its file again after the services start"


def test_a_failing_reload_never_fails_the_update():
    line = next(l for l in SCRIPT.read_text(encoding="utf-8").splitlines() if "caddy reload" in l)
    assert line.rstrip().endswith("|| true"), line

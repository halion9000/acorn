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
        f"say() {{ echo \"$*\"; }}\nREPO={tmp_path.as_posix()}\n"
        f"eval \"$(sed -n '/^ensure_ingest_dsn() {{/,/^}}/p' {SCRIPT.as_posix()})\"\n"
        "ensure_ingest_dsn; echo \"exit=$?\"\n"
    )
    out = subprocess.run([BASH, "-c", program], capture_output=True, text=True, timeout=60)
    return out.stdout, (tmp_path / ".env").read_text()


def test_it_derives_the_connection_from_the_migration_url_and_keeps_the_other_lines(tmp_path):
    said, env = run_helper(tmp_path, "ONE=1\nAZURE_MIGRATION_DATABASE_URL=postgresql+asyncpg://admin:p%40ss@db.example:5432/aisoc?ssl=require\nTWO=2\n")
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
    services = [line for line in compose.splitlines() if line.startswith("  ") and not line.startswith("   ") and line.rstrip().endswith(":") and not line.strip().startswith("#")]
    assert len(services) == len(set(services)), "no service is defined twice (that stopped an update on 2026-10-31)"


def run_plain(tmp_path: Path, env_text: str):
    (tmp_path / ".env").write_text(env_text)
    program = (
        f"say() {{ echo \"$*\"; }}\nREPO={tmp_path.as_posix()}\n"
        f"eval \"$(sed -n '/^ensure_plain_database_url() {{/,/^}}/p' {SCRIPT.as_posix()})\"\n"
        "ensure_plain_database_url; echo \"exit=$?\"\n"
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
    assert "AZURE_MIGRATION_DATABASE_URL=postgresql+asyncpg://admin:pw@db.example:5432/aisoc?ssl=require" in lines, "the migration address keeps it: its own tool reads it"
    assert "ONE=1" in lines and "TWO=2" in lines


def test_other_settings_on_the_address_stay_and_an_address_without_ssl_is_left_alone(tmp_path):
    _, env = run_plain(tmp_path, "AZURE_DATABASE_URL=postgresql+asyncpg://u:p@h:5432/aisoc?ssl=require&application_name=acorn\n")
    assert env.strip() == "AZURE_DATABASE_URL=postgresql+asyncpg://u:p@h:5432/aisoc?application_name=acorn"
    said, env = run_plain(tmp_path / "x" if (tmp_path / "x").mkdir() is None else tmp_path, "AZURE_DATABASE_URL=postgresql+asyncpg://u:p@h:5432/aisoc\n")
    assert "removed" not in said and env.strip() == "AZURE_DATABASE_URL=postgresql+asyncpg://u:p@h:5432/aisoc"


def test_every_service_that_gets_the_database_address_also_gets_ssl_required_through_pgsslmode():
    compose = (SCRIPT.parent / "docker-compose.azure.yml").read_text()
    with_url = compose.count("DATABASE_URL: ${AZURE_DATABASE_URL:?set AZURE_DATABASE_URL}")
    assert with_url >= 9
    assert compose.count("PGSSLMODE: require") == with_url, "one PGSSLMODE for each service that gets the address"

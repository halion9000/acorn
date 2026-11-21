"""Built-in triage of vendor alerts: ATT&CK techniques from titles, and by-design alerts resolved as benign."""

import os
import uuid

import pytest
from app.services.alert_triage import by_design_reason, technique_for


def test_titles_that_really_are_one_technique_get_it_and_the_rest_do_not():
    assert technique_for("Email reported by user as malware or phish") == ("T1566", "Initial Access")
    assert technique_for("Atypical travel") == ("T1078", "Initial Access")
    assert technique_for("Microsoft 365: User Authentication from New Country") == ("T1078", "Initial Access")
    assert technique_for("Potential Unsecured Credentials in Files") == ("T1552.001", "Credential Access")
    assert technique_for("Windows Service: 'Microsoft Defender Antivirus Service (WinDefend)' is Stopped a") == ("T1562.001", "Defense Evasion")
    assert technique_for("Password Spray") == ("T1110.003", "Credential Access")
    # Not honestly one technique: left alone.
    for title in ("BitLocker encryption is disabled for disk volume: 'C:'", "Process: 'HuntressAgent' does not exist", "Disk Volume Usage for /System/Volumes/Data (95%) is greater", "", None):
        assert technique_for(title) is None


def test_only_alerts_that_are_true_by_design_need_no_person():
    by_design = [
        "Disk Volume Usage for /Library/Developer/CoreSimulator/Volumes/iOS_24A434 (97%) is greater than or equal to 90% from 2026",
        "Disk Volume Free space for /Library/Developer/CoreSimulator/Cryptex/Images/bundle/SimRunti (3%) is less",
        "Disk Volume Usage for /private/var/run/com.apple.security.cryptexd/mnt/com.apple.iPhoneOS. (100%) is greater",
        "Disk Volume Free space for /Volumes/Recovery (100%) is greater than or equal to 90%",
        "Disk Volume Usage for /Volumes/ChatGPT Installer (100%) is greater than or equal to 90%",
        "Disk Volume Usage for /Volumes/FieryCommandWorkStation (97%) is greater than or equal to 90%",
        "Email reported by user as junk",
        "Email reported by user as not junk",
    ]
    for title in by_design:
        assert by_design_reason(title), title
    real = [
        "Disk Volume Usage for /System/Volumes/Data (95%) is greater than or equal to 90% from 2026",  # the machine's real disk
        "Disk Volume Usage for /Volumes/Backup (96%) is greater than or equal to 90%",  # an external drive that is nearly full
        "Disk Volume Usage for C: (93%) is greater than or equal to 90%",
        "Email reported by user as malware or phish",
        "Process: 'HuntressAgent' does not exist",
    ]
    for title in real:
        assert by_design_reason(title) is None, title


PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")


@pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")
@pytest.mark.asyncio
async def test_the_sweeps_map_and_resolve_only_what_they_should():
    from app.services.alert_triage import sweep_attack_mapping, sweep_by_design
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    tid, tag = uuid.uuid4(), uuid.uuid4().hex[:8]
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    titles = {
        "phish": "Email reported by user as malware or phish",
        "junk": "Email reported by user as junk",
        "sim": "Disk Volume Usage for /Library/Developer/CoreSimulator/Volumes/iOS_1 (97%) is greater than or equal to 90%",
        "data": "Disk Volume Usage for /System/Volumes/Data (95%) is greater than or equal to 90%",
        "bitlocker": "BitLocker encryption is disabled for disk volume: 'C:'",
    }
    try:
        async with engine.begin() as c:
            await c.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await c.execute(text("insert into tenants (id, name, slug, mssp_role) values (:i, :n, :s, 'parent')"), {"i": tid, "n": f"tri-{tag}", "s": f"tri-{tag}"})
            for title in titles.values():
                await c.execute(
                    text("insert into alerts (id, tenant_id, title, severity, status, created_at, updated_at, event_time, first_seen) values (:a, :t, :title, 'low', 'new', now(), now(), now(), now())"),
                    {"a": uuid.uuid4(), "t": tid, "title": title},
                )
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await db.execute(text("select set_config('app.rls_fail_closed', 'off', false)"))
            assert await sweep_attack_mapping(db) >= 1
            assert await sweep_by_design(db) >= 2
            await db.commit()
        async with engine.begin() as c:
            await c.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            result = await c.execute(text("select title, status, disposition, mitre_techniques::text, enrichment_data::text from alerts where tenant_id = :t"), {"t": tid})
            rows = {r[0]: r[1:] for r in result.all()}
        assert rows[titles["phish"]][0] == "new" and "T1566" in rows[titles["phish"]][2]
        assert rows[titles["junk"]][0] == "resolved" and rows[titles["junk"]][1] == "benign" and "auto_triage" in rows[titles["junk"]][3]
        assert rows[titles["sim"]][0] == "resolved"
        assert rows[titles["data"]][0] == "new" and rows[titles["bitlocker"]][0] == "new"
        assert rows[titles["bitlocker"]][2] in ("[]", "null", None)
    finally:
        async with engine.begin() as c:
            await c.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await c.execute(text("delete from alerts where tenant_id = :t"), {"t": tid})
            await c.execute(text("delete from tenants where id = :t"), {"t": tid})
        await engine.dispose()

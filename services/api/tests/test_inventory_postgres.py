"""The inventory endpoints on a REAL Postgres (AISOC_TEST_PG_URL, a DISPOSABLE fully migrated database): items live under their client's tenant, movements leave a history, imports are repeatable."""

from __future__ import annotations

import csv
import io
import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import inventory as ep
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database"),
]


async def world():
    """A Live Oak-like owner with two clients, plus a stranger with a client of its own."""
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    owner, acme, birch, stranger, stranger_client = (uuid.uuid4() for _ in range(5))
    tag = uuid.uuid4().hex[:8]
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for tid, name, parent in (
            (owner, "Live Oak", None),
            (acme, "Acme Dental, LLC", owner),
            (birch, "Birch Law", owner),
            (stranger, "Other MSP", None),
            (stranger_client, "Their Client", stranger),
        ):
            await conn.execute(
                text("insert into tenants (id, name, slug, parent_tenant_id) values (:t, :n, :s, :p)"),
                {"t": tid, "n": name, "s": f"inv-{tag}-{str(tid)[:6]}", "p": parent},
            )
    user = SimpleNamespace(tenant_id=owner, email="hal@goliveoak.com")
    return engine, user, SimpleNamespace(owner=owner, acme=acme, birch=birch, stranger=stranger, stranger_client=stranger_client)


async def cleanup(engine, ids):
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(text("delete from devices where tenant_id = any(:t)"), {"t": list(ids)})
        await conn.execute(text("delete from tenants where id = any(:t)"), {"t": list(ids)})
    await engine.dispose()


def ls(user, db, **kw):
    """The list endpoint with every parameter given (called directly, the defaults would be FastAPI Query objects)."""
    args = {
        "kind": "stock",
        "client": None,
        "status": None,
        "category": None,
        "tag": None,
        "search": None,
        "page": 1,
        "page_size": 50,
        **kw,
    }
    return ep.list_items(user, db, **args)


def exp(user, db, **kw):
    args = {"kind": "stock", "client": None, "status": None, "category": None, "tag": None, "search": None, **kw}
    return ep.export_items(user, db, **args)


def item(**over):
    base = {"name": "Dell Pro Max 16", "serial": "BSH7SB4", "category": "Computers", "model": "Pro Max 16"}
    return ep.ItemIn.model_validate({**base, **over})


async def test_an_item_is_stored_under_its_clients_tenant_and_the_list_says_which_client_and_what_is_live_oaks_own():
    engine, user, w = await world()
    try:
        async with AsyncSession(engine) as db:
            mine = await ep.create_item(item(name="Spare switch", serial="SW1234"), user, db)
            theirs = await ep.create_item(item(client_id=w.acme), user, db)
            assert (mine.client_id, mine.client_name, theirs.client_id, theirs.client_name) == (None, None, w.acme, "Acme Dental, LLC")
            everything = await ls(user, db)
            assert everything.total == 2 and {i.name for i in everything.items} == {"Spare switch", "Dell Pro Max 16"}
            only_acme = await ls(user, db, client=str(w.acme))
            assert [i.client_name for i in only_acme.items] == ["Acme Dental, LLC"]
            only_own = await ls(user, db, client="own")
            assert [i.name for i in only_own.items] == ["Spare switch"]
            row = (await db.execute(text("select tenant_id from inventory_items where id = :i"), {"i": theirs.id})).scalar_one()
            assert row == w.acme, "stored under the client's own tenant, which is what keeps a future client portal to its own items"
    finally:
        await cleanup(engine, [w.owner, w.acme, w.birch, w.stranger, w.stranger_client])


async def test_filters_search_status_and_pages_narrow_the_list_and_the_summary_counts_the_whole_scope():
    engine, user, w = await world()
    try:
        async with AsyncSession(engine) as db:
            for i in range(5):
                await ep.create_item(
                    item(name=f"Drive {i}", serial=f"DRV{i}000", category="Drives", tags=["spare"] if i < 2 else []), user, db
                )
            await ep.create_item(item(name="UPS", serial="UPS0001", category="Power", status="checked_out", person="Pat"), user, db)
            nuc = await ep.create_item(item(kind="nuc", name="NUC-X", serial="NUC0001", site="Austin"), user, db)
            page = await ls(user, db, page_size=4)
            assert (page.total, len(page.items), page.pages) == (6, 4, 2)
            assert page.summary.by_status == {"checked_in": 5, "checked_out": 1} and ("Drives", 5) in page.summary.categories
            assert [i.name for i in (await ls(user, db, search="pat")).items] == ["UPS"], "search reaches the person holding it"
            assert (await ls(user, db, status="checked_out")).total == 1
            assert (await ls(user, db, category="Drives", tag="spare")).total == 2
            assert (await ls(user, db, search="%")).total == 0, "a percent sign in a search is a literal percent, not a wildcard"
            nucs = await ls(user, db, kind="nuc")
            assert [i.id for i in nucs.items] == [nuc.id] and nucs.items[0].site == "Austin"
    finally:
        await cleanup(engine, [w.owner, w.acme, w.birch, w.stranger, w.stranger_client])


async def test_checking_out_and_in_follows_the_rules_records_who_and_when_and_keeps_a_history():
    engine, user, w = await world()
    try:
        async with AsyncSession(engine) as db:
            made = await ep.create_item(item(client_id=w.birch), user, db)
            out = await ep.check_out(
                made.id,
                ep.MoveIn(person="Pat Jones", ticket_url="https://liveoakit.halopsa.com/tickets?id=1", note="for the new hire"),
                user,
                db,
            )
            assert (out.status, out.person, out.ticket_url) == (
                "checked_out",
                "Pat Jones",
                "https://liveoakit.halopsa.com/tickets?id=1",
            ) and out.checked_out_at is not None
            with pytest.raises(HTTPException) as again:
                await ep.check_out(made.id, ep.MoveIn(person="Someone Else"), user, db)
            assert again.value.status_code == 409
            back = await ep.check_in(made.id, ep.MoveIn(note="returned with charger"), user, db)
            assert back.status == "checked_in" and back.checked_in_at is not None
            with pytest.raises(HTTPException):
                await ep.check_in(made.id, ep.MoveIn(), user, db)
            events = await ep.item_events(made.id, user, db)
            assert [e.event for e in events] == ["checked_in", "checked_out", "created"]
            assert events[1].person == "Pat Jones" and events[1].note == "for the new hire" and events[0].actor == "hal@goliveoak.com"
            retired = await ep.update_item(made.id, ep.ItemPatch(status="retired"), user, db)
            assert retired.status == "retired"
            with pytest.raises(HTTPException):
                await ep.check_out(made.id, ep.MoveIn(), user, db)
            assert (await ep.item_events(made.id, user, db))[0].event == "retired"
    finally:
        await cleanup(engine, [w.owner, w.acme, w.birch, w.stranger, w.stranger_client])


async def test_an_item_can_be_changed_and_moved_to_another_client_or_back_to_live_oak_and_its_history_goes_with_it():
    engine, user, w = await world()
    try:
        async with AsyncSession(engine) as db:
            made = await ep.create_item(item(), user, db)
            changed = await ep.update_item(made.id, ep.ItemPatch(site="Dallas", notes="new battery", tags=["loaner"]), user, db)
            assert (changed.site, changed.notes, changed.tags) == ("Dallas", "new battery", ["loaner"]) and changed.serial == "BSH7SB4"
            moved = await ep.update_item(made.id, ep.ItemPatch(client_id=w.acme), user, db)
            assert (moved.client_id, moved.client_name) == (w.acme, "Acme Dental, LLC")
            owners = (
                (await db.execute(text("select distinct tenant_id from inventory_events where item_id = :i"), {"i": made.id}))
                .scalars()
                .all()
            )
            assert owners == [w.acme], "the history follows the item, so the client sees it all"
            home = await ep.update_item(made.id, ep.ItemPatch(move_to_own=True), user, db)
            assert home.client_id is None
            with pytest.raises(HTTPException) as e:
                await ep.update_item(made.id, ep.ItemPatch(client_id=w.stranger_client), user, db)
            assert e.value.status_code == 404
    finally:
        await cleanup(engine, [w.owner, w.acme, w.birch, w.stranger, w.stranger_client])


async def test_an_organization_never_sees_or_changes_another_organizations_stock():
    engine, user, w = await world()
    try:
        async with AsyncSession(engine) as db:
            theirs = SimpleNamespace(tenant_id=w.stranger, email="x@other.com")
            hidden = await ep.create_item(item(name="Their laptop", client_id=w.stranger_client), theirs, db)
            assert (await ls(user, db)).total == 0
            for call in (
                ep.check_out(hidden.id, ep.MoveIn(), user, db),
                ep.update_item(hidden.id, ep.ItemPatch(name="mine now"), user, db),
                ep.item_events(hidden.id, user, db),
            ):
                with pytest.raises(HTTPException) as e:
                    await call
                assert e.value.status_code == 404
            with pytest.raises(HTTPException):
                await ls(user, db, client=str(w.stranger_client))
    finally:
        await cleanup(engine, [w.owner, w.acme, w.birch, w.stranger, w.stranger_client])


LIST = (
    '"ID","Customer","EntryName","SerialNo","Quantity","Notes","Status"\n'
    '"1","Acme Dental","Dell Laptop","AAA1111","1","<p>charger missing</p>","Checked Out"\n'
    '"2","Birch Law Firm","Monitor","BBB2222","2",,"Checked In"\n'
    '"3","LO Inventory (Office)","Cables","","10",,"Checked In"\n'
    '"4","Unknown Co","Dock","CCC3333","1",,"Archived"\n'
    '"5","Acme Dental",,,,,\n'
)


async def test_a_dry_run_says_where_each_customer_would_go_and_stores_nothing_then_the_import_is_repeatable():
    engine, user, w = await world()
    try:
        async with AsyncSession(engine) as db:
            dry = await ep.import_items(ep.ImportIn(kind="stock", csv_text=LIST, dry_run=True), user, db)
            by_name = {c.name: c for c in dry.customers}
            assert (dry.rows, dry.created, dry.skipped) == (5, 4, 1) and dry.problems and "line 6" in dry.problems[0]
            assert (by_name["Acme Dental"].placed, by_name["Acme Dental"].client_id) == ("exact", w.acme)
            assert by_name["LO Inventory (Office)"].placed == "own" and by_name["Unknown Co"].placed == "unmatched"
            assert by_name["Birch Law Firm"].placed == "unmatched" and by_name["Birch Law Firm"].suggestions[0]["client_id"] == str(w.birch)
            assert (await ls(user, db)).total == 0, "a dry run stores nothing"
            done = await ep.import_items(ep.ImportIn(kind="stock", csv_text=LIST, dry_run=False), user, db)
            assert (done.created, done.updated) == (4, 0)
            again = await ep.import_items(ep.ImportIn(kind="stock", csv_text=LIST, dry_run=False), user, db)
            assert (again.created, again.updated) == (0, 4), "importing the same list again updates, it never duplicates"
            listed = await ls(user, db)
            assert listed.total == 4
            laptop = next(i for i in listed.items if i.name == "Dell Laptop")
            assert (laptop.client_id, laptop.status, laptop.notes, laptop.source) == (w.acme, "checked_out", "charger missing", "csv")
            unmatched = next(i for i in listed.items if i.name == "Dock")
            assert (unmatched.client_id, unmatched.customer_name, unmatched.status) == (
                None,
                "Unknown Co",
                "retired",
            ), "kept under Live Oak with the name as written, not dropped"
            assert listed.summary.unmatched_customers >= 2
    finally:
        await cleanup(engine, [w.owner, w.acme, w.birch, w.stranger, w.stranger_client])


async def test_a_person_can_place_an_unmatched_customer_and_a_per_client_file_takes_the_chosen_client():
    engine, user, w = await world()
    try:
        async with AsyncSession(engine) as db:
            await ep.import_items(
                ep.ImportIn(kind="stock", csv_text=LIST, dry_run=False, mapping={"birch law firm": str(w.birch), "unknown co": "skip"}),
                user,
                db,
            )
            names = {i.name: i for i in (await ls(user, db)).items}
            assert names["Monitor"].client_id == w.birch and "Dock" not in names
            per_client = '"EntryName","Device Model","Deployed To","SerialNo","Status"\n"X1 Carbon","X1 Carbon 13th Gen","Arjun Barua","PF5QMPC","Checked Out"\n'
            await ep.import_items(ep.ImportIn(kind="stock", csv_text=per_client, default_client_id=w.birch, dry_run=False), user, db)
            carbon = next(i for i in (await ls(user, db, client=str(w.birch))).items if i.name == "X1 Carbon")
            assert (carbon.person, carbon.model, carbon.client_name) == ("Arjun Barua", "X1 Carbon 13th Gen", "Birch Law")
            with pytest.raises(HTTPException) as e:
                await ep.import_items(
                    ep.ImportIn(kind="stock", csv_text=LIST, mapping={"x": str(w.stranger_client)}, dry_run=True), user, db
                )
            assert e.value.status_code == 404
            with pytest.raises(HTTPException) as bad:
                await ep.import_items(ep.ImportIn(kind="stock", csv_text=LIST, mapping={"x": "not-a-client"}, dry_run=True), user, db)
            assert bad.value.status_code == 422
    finally:
        await cleanup(engine, [w.owner, w.acme, w.birch, w.stranger, w.stranger_client])


async def test_an_item_is_linked_to_the_machine_it_is_by_serial_number_or_by_the_ninjaone_page_its_list_carried():
    engine, user, w = await world()
    dev_serial, dev_ninja = uuid.uuid4(), uuid.uuid4()
    try:
        async with engine.begin() as conn:
            await conn.execute(text("set local session_replication_role = replica"))
            await conn.execute(
                text(
                    "insert into devices (id, tenant_id, serial_number, hostname, last_seen, first_seen, created_at) values (:i, :t, 'bsh7sb4', 'AUSTIN-LAP-01', now(), now(), now())"
                ),
                {"i": dev_serial, "t": w.acme},
            )
            await conn.execute(
                text(
                    "insert into devices (id, tenant_id, hostname, last_seen, first_seen, created_at) values (:i, :t, 'DALLAS-PC', now(), now(), now())"
                ),
                {"i": dev_ninja, "t": w.acme},
            )
            await conn.execute(
                text(
                    "insert into device_sources (id, tenant_id, device_id, vendor, external_id, details, last_seen, created_at) values (gen_random_uuid(), :t, :d, 'ninjaone', '9500', '{}'::jsonb, now(), now())"
                ),
                {"t": w.acme, "d": dev_ninja},
            )
        async with AsyncSession(engine) as db:
            await ep.create_item(item(client_id=w.acme), user, db)
            await ep.create_item(
                item(
                    client_id=w.acme, name="Other", serial="ZZZ9999", ninja_url="https://app.ninjarmm.com/#/deviceDashboard/9500/overview"
                ),
                user,
                db,
            )
            await ep.create_item(item(client_id=w.acme, name="Unknown", serial="NOPE0001"), user, db)
            links = {i.name: i.device for i in (await ls(user, db)).items}
            assert (links["Dell Pro Max 16"].hostname, links["Dell Pro Max 16"].how) == ("AUSTIN-LAP-01", "serial")
            assert (links["Other"].hostname, links["Other"].how) == ("DALLAS-PC", "ninjaone")
            assert links["Unknown"] is None
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("set local session_replication_role = replica"))
            await conn.execute(text("delete from device_sources where tenant_id = :t"), {"t": w.acme})
        await cleanup(engine, [w.owner, w.acme, w.birch, w.stranger, w.stranger_client])


async def test_the_export_is_a_csv_of_the_filtered_list_and_a_cell_that_starts_like_a_formula_is_quoted():
    engine, user, w = await world()
    try:
        async with AsyncSession(engine) as db:
            await ep.create_item(item(name='=HYPERLINK("http://evil")', client_id=w.acme, serial="EXP0001"), user, db)
            await ep.create_item(item(name="Plain", serial="EXP0002"), user, db)
            response = await exp(user, db, client=str(w.acme))
            rows = list(csv.DictReader(io.StringIO(response.body.decode())))
            assert response.media_type == "text/csv" and len(rows) == 1
            assert rows[0]["client"] == "Acme Dental, LLC" and rows[0]["name"].startswith("'=")
            everything = list(csv.DictReader(io.StringIO((await exp(user, db)).body.decode())))
            assert {r["client"] for r in everything} == {"Acme Dental, LLC", "Live Oak"}
    finally:
        await cleanup(engine, [w.owner, w.acme, w.birch, w.stranger, w.stranger_client])


NUCS = (
    '"ID","Customer","Computer Name","Serial No.","Status"\n'
    '"1","Acme Dental","NUC-A","KAMRUI","CheckedOut"\n'
    '"2","Acme Dental","NUC-B","KAMRUI","CheckedOut"\n'
    '"3","Acme Dental","NUC-C","Default string","CheckedIn"\n'
    '"4","Acme Dental","NUC-D","MXL5193139","CheckedOut"\n'
    '"5","Acme Dental","NUC-OLD-CUSTOM-1","","CheckedOut"\n'
    '"6","Acme Dental","NUC-OLD-CUSTOM-2","","CheckedOut"\n'
)


async def test_nucs_that_share_a_placeholder_serial_or_have_none_stay_separate_through_an_import_and_a_re_import():
    engine, user, w = await world()
    try:
        async with AsyncSession(engine) as db:
            first = await ep.import_items(ep.ImportIn(kind="nuc", csv_text=NUCS, dry_run=False), user, db)
            assert (first.created, first.updated) == (
                6,
                0,
            ), "six different NUCs, whatever their serial field says, including the old custom ones with none"
            again = await ep.import_items(ep.ImportIn(kind="nuc", csv_text=NUCS, dry_run=False), user, db)
            assert (again.created, again.updated) == (0, 6), "found again by their list ids"
            assert (await ls(user, db, kind="nuc")).total == 6
            # A row with no list id still finds its item by a real, unshared serial number, and never by a shared one or by none.
            no_ids = '"Customer","Computer Name","Serial No.","Status"\n"Acme Dental","NUC-D renamed","MXL5193139","CheckedIn"\n"Acme Dental","NUC-X","KAMRUI","CheckedIn"\n"Acme Dental","NUC-Y","","CheckedIn"\n'
            third = await ep.import_items(ep.ImportIn(kind="nuc", csv_text=no_ids, dry_run=False), user, db)
            assert (third.created, third.updated) == (2, 1)
            names = {i.name: i for i in (await ls(user, db, kind="nuc")).items}
            assert "NUC-D renamed" in names and "NUC-D" not in names and names["NUC-D renamed"].status == "checked_in"
            assert {"NUC-X", "NUC-Y", "NUC-OLD-CUSTOM-1", "NUC-OLD-CUSTOM-2"} <= set(names)
            assert all(i.device is None for i in names.values())
    finally:
        await cleanup(engine, [w.owner, w.acme, w.birch, w.stranger, w.stranger_client])

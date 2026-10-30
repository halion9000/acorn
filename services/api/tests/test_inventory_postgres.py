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


async def test_a_bulk_edit_moves_many_items_to_one_client_with_their_history_and_changes_only_what_was_sent():
    engine, user, w = await world()
    try:
        async with AsyncSession(engine) as db:
            a = await ep.create_item(item(name="A1", serial="S-A1", category="Drives", tags=["keep"]), user, db)
            b = await ep.create_item(item(name="B1", serial="S-B1", client_id=w.birch, site="Austin"), user, db)
            c = await ep.create_item(item(name="C1", serial="S-C1"), user, db)
            out = await ep.bulk_update(ep.BulkIn(ids=[a.id, b.id, uuid.uuid4()], client_id=w.acme, add_tags=["moved", "keep"]), user, db)
            assert (out.changed, out.unchanged, out.not_found) == (2, 0, 1)
            rows = {i.name: i for i in (await ls(user, db)).items}
            assert rows["A1"].client_id == w.acme and rows["B1"].client_id == w.acme and rows["C1"].client_id is None
            assert rows["A1"].tags == ["keep", "moved"], "a tag already there is not added twice"
            assert rows["A1"].category == "Drives" and rows["B1"].site == "Austin", "fields that were not sent are untouched"
            only_acme = await ls(user, db, client=str(w.acme))
            assert only_acme.total == 2
            history = await ep.item_events(a.id, user, db)
            assert history[0].event == "moved" and "bulk edit" in (history[0].note or ""), "the history follows the item to its new client"
            again = await ep.bulk_update(ep.BulkIn(ids=[a.id, b.id], client_id=w.acme), user, db)
            assert (again.changed, again.unchanged) == (0, 2)
            home = await ep.bulk_update(ep.BulkIn(ids=[a.id], move_to_own=True), user, db)
            assert home.changed == 1 and (await ls(user, db, client="own")).total == 2
            with pytest.raises(HTTPException) as nobody:
                await ep.bulk_update(ep.BulkIn(ids=[c.id]), user, db)
            assert nobody.value.status_code == 422
            with pytest.raises(HTTPException) as stranger:
                await ep.bulk_update(ep.BulkIn(ids=[c.id], client_id=w.stranger_client), user, db)
            assert stranger.value.status_code == 404
    finally:
        await cleanup(engine, [w.owner, w.acme, w.birch, w.stranger, w.stranger_client])


async def test_the_unmatched_filter_lists_items_whose_customer_was_not_matched_to_a_client():
    engine, user, w = await world()
    try:
        async with AsyncSession(engine) as db:
            await ep.create_item(item(name="Mystery", serial="S-M1", customer_name="Acme Dntl"), user, db)
            await ep.create_item(item(name="Ours", serial="S-M2"), user, db)
            await ep.create_item(item(name="Theirs", serial="S-M3", client_id=w.acme, customer_name="Acme Dental"), user, db)
            unmatched = await ls(user, db, client="unmatched")
            assert [i.name for i in unmatched.items] == ["Mystery"]
            assert (await exp(user, db, client="unmatched")).body.decode().count("Mystery") == 1
    finally:
        await cleanup(engine, [w.owner, w.acme, w.birch, w.stranger, w.stranger_client])


async def add_device(conn, tenant, hostname, serial, os_name, model, *vendors):
    did = uuid.uuid4()
    await conn.execute(
        text(
            "insert into devices (id, tenant_id, serial_number, hostname, os, model, last_seen, first_seen, created_at) "
            "values (:i, :t, :s, :h, :o, :m, now(), now() - interval '40 days', now())"
        ),
        {"i": did, "t": tenant, "s": serial, "h": hostname, "o": os_name, "m": model},
    )
    for n, v in enumerate(vendors):
        await conn.execute(
            text(
                "insert into device_sources (id, tenant_id, device_id, vendor, external_id, details, last_seen, created_at) "
                "values (gen_random_uuid(), :t, :d, :v, :x, '{}'::jsonb, now(), now())"
            ),
            {"t": tenant, "d": did, "v": v, "x": f"{hostname}-{n}"},
        )
    return did


async def test_syncing_devices_adds_what_is_not_on_the_lists_as_checked_out_and_matches_what_is():
    engine, user, w = await world()
    try:
        async with engine.begin() as conn:
            await add_device(conn, w.acme, "ACME-LAP-1", "SN-LISTED-1", "Windows 11 Pro", "Latitude 5440", "ninjaone")
            await add_device(conn, w.acme, "ACME-LAP-2", "SN-NEW-2", "Windows 10 Pro", "OptiPlex 7010", "ninjaone")
            await add_device(conn, w.acme, "Acme-Mac", "SN-MAC-3", "macOS 14.5", "MacBookPro18,3", "addigy", "ninjaone")
            await add_device(conn, w.birch, "Birch-iPad", "SN-IPAD-4", "iPadOS 17.5", "iPad13,1", "addigy")
            await add_device(conn, w.birch, "Birch-iPhone", "SN-PHONE-5", None, "iPhone14,2", "addigy")
            await add_device(conn, w.birch, "BIRCH-DC", "SN-SERVER-6", "Windows Server 2022", "PowerEdge", "ninjaone")
            await add_device(conn, w.birch, "birch-tv", "SN-TV-7", "tvOS 17", "AppleTV", "addigy")
            await add_device(conn, w.birch, "NO-SERIAL-PC", None, "Windows 11 Pro", "Custom", "ninjaone")
            await add_device(conn, w.birch, "huntress-only", "SN-H-8", "Windows 11 Pro", "X", "huntress")
        async with AsyncSession(engine) as db:
            await ep.create_item(item(name="Dell from the list", serial="sn-listed-1", status="checked_in", client_id=w.acme), user, db)
            preview = await ep.sync_devices_endpoint(ep.SyncIn(dry_run=True), user, db)
            assert (preview.devices, preview.matched, preview.matched_in_stock, preview.created, preview.no_serial) == (6, 1, 1, 5, 1)
            assert preview.by_category == {"Mac": 1, "Windows computer": 3, "iPad": 1, "iPhone": 1}
            assert (await ls(user, db)).total == 1, "a preview adds nothing"

            done = await ep.sync_devices_endpoint(ep.SyncIn(dry_run=False), user, db)
            assert (done.created, done.matched) == (5, 1)
            everything = await ls(user, db, page_size=200)
            by_name = {i.name: i for i in everything.items}
            assert everything.total == 6 and "Dell from the list" in by_name
            assert by_name["Dell from the list"].status == "checked_in", "a listed item is left exactly as it was"
            mac = by_name["Acme-Mac"]
            assert (mac.status, mac.source, mac.category, mac.client_id, mac.tags) == (
                "checked_out",
                "device",
                "Mac",
                w.acme,
                ["Addigy", "NinjaOne"],
            )
            assert mac.checked_out_at is not None and mac.serial == "SN-MAC-3"
            assert by_name["Birch-iPad"].client_id == w.birch and by_name["Birch-iPhone"].category == "iPhone"
            assert by_name["NO-SERIAL-PC"].serial is None
            assert {"BIRCH-DC", "birch-tv", "huntress-only"}.isdisjoint(
                by_name
            ), "servers, TV boxes and other tools' devices are not workstations"
            history = await ep.item_events(mac.id, user, db)
            assert history[0].event == "created" and "NinjaOne" in (history[0].note or "")

            # A second sync adds nothing, refreshes what the tool says, and never overwrites what a person did.
            await ep.check_in(mac.id, ep.MoveIn(note="back in the shop"), user, db)
            async with engine.begin() as conn:
                await conn.execute(text("update devices set hostname = 'Acme-Mac-Renamed' where hostname = 'Acme-Mac'"))
            second = await ep.sync_devices_endpoint(ep.SyncIn(dry_run=False), user, db)
            assert (second.created, second.refreshed, second.matched) == (0, 5, 1)
            after = {i.name: i for i in (await ls(user, db, page_size=200)).items}
            assert "Acme-Mac-Renamed" in after and after["Acme-Mac-Renamed"].status == "checked_in", "a person's check-in survives a sync"
            assert (await ls(user, db, page_size=200)).total == 6
    finally:
        await cleanup(engine, [w.owner, w.acme, w.birch, w.stranger, w.stranger_client])


async def test_a_device_item_that_a_list_import_later_covers_becomes_a_list_item_and_is_not_added_again():
    engine, user, w = await world()
    try:
        async with engine.begin() as conn:
            await add_device(conn, w.acme, "ACME-LAP-9", "SN-LATE-9", "Windows 11 Pro", "Latitude", "ninjaone")
        async with AsyncSession(engine) as db:
            await ep.sync_devices_endpoint(ep.SyncIn(dry_run=False), user, db)
            csv_text = '"Customer","EntryName","Serial","Status"\n"Acme Dental","Latitude from the list","SN-LATE-9","CheckedIn"\n'
            done = await ep.import_items(ep.ImportIn(kind="stock", csv_text=csv_text, dry_run=False), user, db)
            assert (done.created, done.updated) == (0, 1), "found by serial, so the list row and the device are one item"
            again = await ep.sync_devices_endpoint(ep.SyncIn(dry_run=False), user, db)
            assert (again.created, again.matched) == (0, 1)
            rows = (await ls(user, db)).items
            assert len(rows) == 1 and rows[0].source == "csv" and rows[0].status == "checked_in"
    finally:
        await cleanup(engine, [w.owner, w.acme, w.birch, w.stranger, w.stranger_client])

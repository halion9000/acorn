"""Which installed programs are remote management or remote access tools, and what a tool is for a client (its own rule, else the one for every client, else unreviewed)."""

import uuid

import pytest
from app.services import remote_tools as rt

A, B = uuid.uuid4(), uuid.uuid4()


@pytest.mark.parametrize(
    ("name", "publisher", "expected"),
    [
        ("AnyDesk", None, "anydesk"),
        ("AnyDesk ACL", "philandro Software GmbH", "anydesk"),
        ("TeamViewer 15", "TeamViewer", "teamviewer"),
        ("TeamViewer Host", None, "teamviewer"),
        ("ScreenConnect Client (a1b2c3d4e5f6)", "ConnectWise, LLC", "screenconnect"),
        ("ConnectWise Control Client", None, "screenconnect"),
        ("NinjaRMMAgent", "NinjaRMM LLC", "ninjaone"),
        ("NinjaOne Agent", None, "ninjaone"),
        ("AteraAgent", "Atera Networks", "atera"),
        ("Splashtop Streamer", "Splashtop Inc.", "splashtop"),
        ("Splashtop for RMM", None, "splashtop"),
        ("Datto RMM Agent", None, "datto_rmm"),
        ("CentraStage", None, "datto_rmm"),
        ("Kaseya Agent", None, "kaseya_vsa"),
        ("LabTech Remote Agent", None, "connectwise_automate"),
        ("LogMeIn", "LogMeIn, Inc.", "logmein"),
        ("LogMeIn Rescue Technician Console", None, "logmein_rescue"),
        ("Pulseway", None, "pulseway"),
        ("SimpleHelp Remote Support", None, "simplehelp"),
        ("Chrome Remote Desktop Host", "Google LLC", "chrome_remote_desktop"),
        ("VNC Server 6.11", "RealVNC", "vnc_connect"),
        ("UltraVNC", None, "ultravnc"),
        ("TightVNC", None, "tightvnc"),
        ("Zoho Assist - Unattended Agent", None, "zoho_assist"),
        ("Bomgar Jump Client", None, "beyondtrust"),
        ("PuTTY release 0.78", "Simon Tatham", "putty"),
        ("WinSCP 6.3", "Martin Prikryl", "winscp"),
        ("RemotePC Host", None, "remotepc"),
        ("Remote Desktop Manager", "Devolutions inc.", "devolutions_rdm"),
        ("GoTo Resolve Unattended", None, "gotoresolve"),
    ],
)
def test_known_programs_are_recognised(name, publisher, expected):
    found = rt.match_software(name, publisher)
    assert found is not None and found.key == expected, (name, found)


@pytest.mark.parametrize(
    "name",
    ["Microsoft Office 365", "Google Chrome", "Remote Desktop Connection Manager", "Microsoft Remote Desktop", "Mozilla Firefox", "Notepad++", "Adobe Acrobat", "Zoom", "Microsoft Teams", "7-Zip", "", "VMware Tools", "Windows Subsystem for Linux"],
)
def test_ordinary_programs_and_microsofts_own_remote_desktop_are_not_flagged(name):
    assert rt.match_software(name) is None


def test_the_publisher_can_settle_an_ambiguous_name_but_a_publisher_alone_never_matches():
    assert rt.match_software("Agent") is None  # a bare name says nothing
    assert rt.match_software("Agent", "Kaseya Corporation").key == "kaseya_vsa"  # the publisher settles it
    assert rt.match_software("Unattended Agent", "Zoho Assist").key == "zoho_assist"
    assert rt.match_software(None, "TeamViewer") is None  # a publisher alone, with no program, never matches


def test_a_device_is_reported_with_each_tool_once_and_the_version_seen():
    software = [
        {"name": "Google Chrome", "version": "130"},
        {"name": "AnyDesk", "version": "8.0.1"},
        {"name": "AnyDesk ACL", "version": ""},  # same tool again, no version: the first one stays
        {"name": "TeamViewer Host", "version": "15.2"},
        "not a dict",
        {"name": None},
    ]
    assert rt.tools_on_device(software) == [rt.Found("anydesk", "8.0.1"), rt.Found("teamviewer", "15.2")]


def test_a_second_entry_fills_in_a_missing_version():
    assert rt.tools_on_device([{"name": "AnyDesk"}, {"name": "AnyDesk", "version": "7.1"}]) == [rt.Found("anydesk", "7.1")]


def test_a_device_with_nothing_of_interest_has_no_tools_and_a_huge_version_is_cut():
    assert rt.tools_on_device([{"name": "Notepad++"}]) == []
    assert rt.tools_on_device([{"name": "AnyDesk", "version": "9" * 500}])[0].version == "9" * 60


def test_the_catalog_has_unique_keys_valid_patterns_and_every_tool_in_the_screenshot():
    keys = [t.key for t in rt.CATALOG]
    assert len(keys) == len(set(keys))
    for name in ("AnyDesk", "TeamViewer", "ScreenConnect", "Splashtop", "Atera", "Kaseya (VSA)", "ConnectWise RMM", "WinSCP", "PuTTY", "Zoho Assist", "SimpleHelp", "Pulseway", "RemotePC", "LogMeIn"):
        assert any(t.name.startswith(name) or name.startswith(t.name) for t in rt.CATALOG), name
    assert rt.tool_by_key("anydesk").name == "AnyDesk" and rt.tool_by_key("nope") is None


def test_one_program_is_never_two_tools():
    for case in ("AnyDesk", "TeamViewer Host", "ScreenConnect Client (x)", "LogMeIn Rescue", "NinjaRMMAgent", "Datto RMM Agent"):
        hits = [t.key for t, ps in rt._COMPILED if any(p.search(case) for p in ps)]
        assert len(hits) == 1, (case, hits)


def test_a_clients_own_rule_beats_the_one_for_everyone_and_nothing_decided_is_unreviewed():
    rules = {("anydesk", None): "blocked", ("anydesk", A): "allowed", ("putty", None): "allowed"}
    assert rt.effective_verdict("anydesk", A, rules) == "allowed"  # A runs it on purpose
    assert rt.effective_verdict("anydesk", B, rules) == "blocked"
    assert rt.effective_verdict("putty", B, rules) == "allowed"
    assert rt.effective_verdict("teamviewer", A, rules) == "unreviewed"
    assert rt.effective_verdict("anydesk", A, {("anydesk", A): "garbage", ("anydesk", None): "blocked"}) == "blocked"  # an unknown value is ignored


MORE = {
    "Quick Assist": "quick_assist", "Remote Help": "remote_help", "RustDesk": "rustdesk", "NoMachine": "nomachine", "Parsec": "parsec", "MeshAgent": "meshcentral", "Mesh Agent": "meshcentral",
    "Tactical RMM Agent": "tactical_rmm", "Action1 Agent": "action1", "Level Agent": "level", "ManageEngine Endpoint Central - Agent": "manageengine_rap", "Remote Access Plus": "manageengine_rap",
    "DameWare Mini Remote Control": "dameware", "ISL Light": "isl_online", "Supremo": "supremo", "UltraViewer": "ultraviewer", "Ammyy Admin": "ammyy", "Remote Utilities - Host": "remote_utilities",
    "DWAgent": "dwservice", "AnyViewer": "anyviewer", "HopToDesk": "hoptodesk", "Sunlogin": "sunlogin", "N-central Windows Agent": "nable_ncentral", "Tailscale": "tailscale", "ZeroTier One": "zerotier",
    "ngrok": "ngrok",
}


@pytest.mark.parametrize(("name", "expected"), sorted(MORE.items()))
def test_the_tools_added_later_are_recognised_and_each_matches_exactly_one_tool(name, expected):
    found = rt.match_software(name)
    assert found is not None and found.key == expected, (name, found)
    hits = [t.key for t, ps in rt._COMPILED if any(p.search(name) for p in ps)]
    assert hits == [expected], (name, hits)


def test_a_program_named_level_is_found_by_its_publisher_alongside_it():
    assert rt.match_software("Level", "Level").key == "level"
    assert rt.match_software("Level") is None  # a bare, common word says nothing


def test_the_catalog_now_has_the_original_list_and_the_additions_with_no_program_claimed_by_two_tools():
    assert len(rt.CATALOG) >= 61
    everything = {**MORE, "AnyDesk": "anydesk", "TeamViewer Host": "teamviewer", "ScreenConnect Client (798cebdb8316a8ff)": "screenconnect", "Splashtop Streamer": "splashtop", "Datto RMM Agent": "datto_rmm", "NinjaRMMAgent": "ninjaone"}
    for name, key in everything.items():
        hits = [t.key for t, ps in rt._COMPILED if any(p.search(name) for p in ps)]
        assert hits == [key], (name, hits)


def test_ordinary_software_is_still_not_flagged_after_the_additions():
    for name in ("Level 3 Communications Client", "Remote Helpdesk Notes", "Quick Access", "Action Camera Viewer", "Microsoft Edge", "Visual Studio Code", "VLC media player"):
        assert rt.match_software(name) is None, name


# ---- tools the owner adds by hand ----------------------------------------------------------------------------------------------------------------------------


def test_a_name_becomes_a_stable_key_and_nothing_else_does():
    assert rt.slug_key("Acme  Remote Desk!") == "custom_acme_remote_desk"
    assert rt.slug_key("***") == "" and rt.slug_key("") == ""
    assert len(rt.slug_key("x" * 200)) <= 60


def test_a_tool_to_add_is_cleaned_and_refused_with_a_reason_the_person_can_act_on():
    assert rt.validate_custom("  Acme   Remote ", "remote_access", " Acme  Remote Desk ", "  Acme Inc ") == ("Acme Remote", "remote_access", "Acme Remote Desk", "Acme Inc")
    for args, words in [
        (("A", "remote_access", "Acme Remote"), "name"),
        (("Acme", "nonsense", "Acme Remote"), "kind"),
        (("Acme", "remote_access", "ab"), "3 to 80"),
        (("Acme", "remote_access", "abc"), "too short"),
        (("Acme", "remote_access", "Acme Remote", "x"), "publisher"),
    ]:
        with pytest.raises(ValueError, match=words):
            rt.validate_custom(*args)


def test_what_the_person_typed_is_matched_as_plain_whole_words_in_any_case_and_never_as_a_pattern():
    t = rt.build_custom("custom_x", "X", "remote_access", "Acme (Remote) Desk+", None)
    import re

    assert re.search(t.patterns[0], "acme (remote) desk+ 2.1", re.I)
    assert not re.search(t.patterns[0], "acme remote desk", re.I)  # the brackets and the plus are part of the name, not pattern characters
    plain = rt.build_custom("custom_y", "Y", "remote_access", "Acme Remote", None)
    assert re.search(plain.patterns[0], "ACME   REMOTE agent", re.I)
    assert not re.search(plain.patterns[0], "Acme Remotely", re.I)  # whole words only


def test_a_publisher_is_only_required_when_the_device_lists_one():
    import re

    t = rt.build_custom("custom_z", "Z", "rmm", "Acme Agent", "Acme Inc")
    assert not re.search(t.patterns[0], "Acme Agent", re.I)  # on the name alone the publisher cannot be confirmed
    assert re.search(t.patterns[0], "Acme Agent Acme Inc", re.I)  # the matcher tries name and publisher together
    assert not re.search(t.patterns[0], "Acme Agent Other Corp", re.I)


def test_a_program_the_built_in_list_already_knows_is_reported_as_covered():
    assert rt.covered_by_builtin("AnyDesk").key == "anydesk"
    assert rt.covered_by_builtin("Acme Remote Desk") is None


def test_the_owners_own_tools_are_visible_to_the_request_that_set_them_and_to_no_other_context():
    import asyncio

    t = rt.build_custom("custom_acme", "Acme Remote", "remote_access", "Acme Remote", None)
    assert rt.tool_by_key("custom_acme") is None

    async def owner_a():
        rt.set_custom([t])
        await asyncio.sleep(0)
        return rt.tool_by_key("custom_acme")

    async def owner_b():
        await asyncio.sleep(0)
        return rt.tool_by_key("custom_acme")

    async def both():
        return await asyncio.gather(asyncio.create_task(owner_a()), asyncio.create_task(owner_b()))

    a, b = asyncio.run(both())
    assert a is not None and a.name == "Acme Remote"
    assert b is None, "another request must not see this owner's tools"
    assert rt.tool_by_key("custom_acme") is None
    assert rt.tool_by_key("anydesk").name == "AnyDesk"  # the built-in list is always there

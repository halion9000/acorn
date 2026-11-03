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

"""Remote management and remote access tools found on client devices, and what the owner has decided about each.

An attacker who gets into a network often installs a remote access tool, or uses one the client already runs, to keep a way back in; a technician's forgotten tool is a way in too. This module knows which
installed programs are such tools (a catalog of names and publishers), turns a device's software list into the tools on it, and decides what each is: ``allowed`` (we run it, or the client does on purpose),
``blocked`` (nothing should be running it) or ``unreviewed`` (nobody decided yet). A blocked tool found on a device raises an alert.

Only the matches are kept, never the whole software list of a device: the list is large and mostly not ours to hold. Matching is by program name (and publisher where the name alone is ambiguous), case
insensitive, on whole words, so ``Remote Desktop Connection Manager`` is not mistaken for AnyDesk and a program called ``Anydeskhelper`` is not silently ignored either (see the tests).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

Verdict = Literal["allowed", "blocked", "unreviewed"]
VERDICTS: tuple[str, ...] = ("allowed", "blocked", "unreviewed")


@dataclass(frozen=True)
class Tool:
    key: str  # stable id used in rules and alerts
    name: str  # how it is shown
    category: str  # rmm | remote_access | remote_support | file_transfer | remote_desktop_manager
    # Regular expressions tried against "<program name>" (and "<program name> <publisher>" where the pattern says so with \b boundaries).
    patterns: tuple[str, ...]


CATALOG: tuple[Tool, ...] = (
    Tool("acronis_remotely", "Acronis Cyber Protect (Remotely)", "remote_support", (r"\bacronis\b.*\b(remote|cyber protect connect|cyber protect.*agent)\b", r"\bremotely\b.*\bacronis\b")),
    Tool("anydesk", "AnyDesk", "remote_access", (r"^anydesk\b", r"\banydesk\b(?!.*manager)")),
    Tool("atera", "Atera", "rmm", (r"\batera\b.*\b(agent|networks)\b", r"^atera\b", r"\bateraagent\b")),
    Tool("aweray", "AweRay (AweSun)", "remote_access", (r"\bawesun\b", r"\baweray\b")),
    Tool("beyondtrust", "BeyondTrust (Bomgar)", "remote_support", (r"\bbomgar\b", r"\bbeyondtrust\b.*\b(remote support|jump client|representative console|endpoint)\b")),
    Tool("chrome_remote_desktop", "Chrome Remote Desktop", "remote_access", (r"\bchrome remote desktop\b",)),
    Tool("connectwise_automate", "ConnectWise Automate (LabTech)", "rmm", (r"\blabtech\b", r"\bconnectwise automate\b", r"\bltsvc\b", r"\bautomate agent\b")),
    Tool("connectwise_rmm", "ConnectWise RMM", "rmm", (r"\bconnectwise rmm\b", r"\bconnectwise.*\bcontinuum\b", r"\bconnectwise manage agent\b")),
    Tool("datto_rmm", "Datto RMM", "rmm", (r"\bdatto rmm\b", r"\bdattoagent\b", r"\bcentrastage\b", r"\bdatto\b.*\bagent\b")),
    Tool("devolutions_rdm", "Devolutions Remote Desktop Manager", "remote_desktop_manager", (r"\bremote desktop manager\b.*\bdevolutions\b", r"\bdevolutions\b.*\bremote desktop manager\b", r"^remote desktop manager\b")),
    Tool("duet_display", "Duet Display", "remote_access", (r"\bduet display\b",)),
    Tool("gotoassist", "GoToAssist", "remote_support", (r"\bgotoassist\b", r"\bgoto assist\b")),
    Tool("gotoresolve", "GoToAssist (GoTo Resolve)", "remote_support", (r"\bgoto resolve\b", r"\bgotoresolve\b")),
    Tool("gotomypc", "GoToMyPC", "remote_access", (r"\bgotomypc\b", r"\bgoto my pc\b")),
    Tool("iperius_remote", "Iperius Remote", "remote_access", (r"\biperius remote\b",)),
    Tool("jumpcloud", "JumpCloud", "rmm", (r"\bjumpcloud\b",)),
    Tool("kaseya_vsa", "Kaseya (VSA)", "rmm", (r"\bkaseya\b", r"\bkaseyad\b", r"\bkaseya agent\b")),
    Tool("logmein", "LogMeIn", "remote_access", (r"^logmein\b(?!.*rescue)", r"\blogmein pro\b", r"\blogmein hamachi\b")),
    Tool("logmein_rescue", "LogMeIn Rescue", "remote_support", (r"\blogmein rescue\b", r"\bgotoassist rescue\b")),
    Tool("nable_ama", "N-able Advanced Monitoring Agent", "rmm", (r"\badvanced monitoring agent\b", r"\bn-able\b.*\bmonitoring\b", r"\bsolarwinds msp\b.*\bagent\b")),
    Tool("nable_take_control", "N-able Take Control", "remote_support", (r"\btake control\b.*\b(n-able|solarwinds|mspa?)\b", r"\bbasic take control\b", r"\bbeanywhere\b")),
    Tool("ninjaone", "NinjaOne (formerly NinjaRMM)", "rmm", (r"\bninjarmm", r"\bninjaone\b", r"\bninja ?rmm agent\b")),
    Tool("pulseway", "Pulseway", "rmm", (r"\bpulseway\b",)),
    Tool("putty", "PuTTY", "remote_access", (r"^putty\b",)),
    Tool("radmin", "RAdmin", "remote_access", (r"\bradmin (server|viewer)\b", r"^radmin\b", r"\bremote administrator\b.*\bfamatech\b")),
    Tool("remotepc", "RemotePC", "remote_access", (r"^remotepc\b", r"\bremotepc (host|viewer)\b")),
    Tool("screenconnect", "ScreenConnect", "remote_support", (r"\bscreenconnect\b", r"\bconnectwise control\b")),
    Tool("simplehelp", "SimpleHelp", "remote_support", (r"\bsimplehelp\b", r"\bsimple-help\b")),
    Tool("splashtop", "Splashtop", "remote_access", (r"\bsplashtop\b",)),
    Tool("superops", "SuperOps", "rmm", (r"\bsuperops\b",)),
    Tool("syncro", "Syncro", "rmm", (r"\bsyncro\b", r"\bkabuto\b")),
    Tool("teamviewer", "TeamViewer", "remote_access", (r"\bteamviewer\b",)),
    Tool("tightvnc", "TightVNC", "remote_access", (r"\btightvnc\b",)),
    Tool("ultravnc", "Ultra VNC", "remote_access", (r"\bultravnc\b", r"\bultra vnc\b")),
    Tool("vnc_connect", "VNC Connect", "remote_access", (r"\bvnc (connect|server|viewer)\b", r"\brealvnc\b")),
    Tool("winscp", "WinSCP", "file_transfer", (r"^winscp\b",)),
    Tool("zoho_assist", "Zoho Assist", "remote_support", (r"\bzoho assist\b", r"\bzohoassist\b", r"\bzoho meeting\b.*\bassist\b")),
)

_BY_KEY = {t.key: t for t in CATALOG}
_COMPILED: list[tuple[Tool, list[re.Pattern[str]]]] = [(t, [re.compile(p, re.IGNORECASE) for p in t.patterns]) for t in CATALOG]


def tool_by_key(key: str) -> Tool | None:
    return _BY_KEY.get(key)


def categories() -> list[str]:
    return sorted({t.category for t in CATALOG})


def match_software(name: str | None, publisher: str | None = None) -> Tool | None:
    """The catalog tool a program is, or None. The name is tried alone first, then name and publisher together; the first tool in the catalog that matches wins (patterns are written so two never do)."""
    text = " ".join((name or "").split())
    if not text:
        return None
    both = f"{text} {' '.join((publisher or '').split())}".strip()
    for tool, patterns in _COMPILED:
        if any(p.search(text) for p in patterns) or (publisher and any(p.search(both) for p in patterns)):
            return tool
    return None


@dataclass(frozen=True)
class Found:
    tool_key: str
    version: str | None


def tools_on_device(software: Iterable[dict[str, object]]) -> list[Found]:
    """The remote tools in a device's software list (each item ``{name, version?, publisher?}``): one entry per tool, with the highest-looking version seen."""
    seen: dict[str, str | None] = {}
    for item in software:
        if not isinstance(item, dict):
            continue
        tool = match_software(str(item.get("name") or ""), str(item.get("publisher") or "") or None)
        if tool is None:
            continue
        version = str(item.get("version") or "").strip()[:60] or None
        if tool.key not in seen or (version and not seen[tool.key]):
            seen[tool.key] = version
    return [Found(k, v) for k, v in sorted(seen.items())]


def effective_verdict(tool_key: str, client_id: uuid.UUID, rules: dict[tuple[str, uuid.UUID | None], str]) -> Verdict:
    """What a tool is for one client: the client's own rule if it has one, otherwise the rule for every client, otherwise unreviewed. ``rules`` maps (tool, client or None for everyone) to a verdict."""
    for scope in (client_id, None):
        v = rules.get((tool_key, scope))
        if v in VERDICTS:
            return v  # type: ignore[return-value]
    return "unreviewed"


# ---- alerts ------------------------------------------------------------------------------------------------------------------------------------------------

RULE_ID = "aisoc-remote-tool-blocked"
RULE_NAME = "Blocked remote tool found"


def host_key(name: str | None) -> str:
    """What a device name is compared by: lower case, without a domain suffix."""
    n = (name or "").strip().lower()
    return n if re.match(r"^(\d{1,3}(\.\d{1,3}){3})$", n) else n.split(".")[0]


def blocked_findings(rows: Iterable[object], rules: dict[tuple[str, uuid.UUID | None], str], now) -> list[tuple[uuid.UUID, object]]:
    """One finding per device a blocked tool was found on: ``rows`` are anything with ``tenant_id``, ``hostname``, ``tool_key``, ``version`` (the stored sightings). The tool is judged for the device's own client
    (its own rule, else the one for every client). The finding's key is the device and tool, so the same sighting is one alert however often it is seen."""
    from app.services.identity_detections import Finding  # noqa: PLC0415

    out: list[tuple[uuid.UUID, object]] = []
    for r in sorted(rows, key=lambda r: (str(r.tenant_id), host_key(r.hostname), r.tool_key)):  # type: ignore[attr-defined]
        tool = _BY_KEY.get(r.tool_key)  # type: ignore[attr-defined]
        if tool is None or effective_verdict(r.tool_key, r.tenant_id, rules) != "blocked":  # type: ignore[attr-defined]
            continue
        version = f" {r.version}" if getattr(r, "version", None) else ""  # type: ignore[attr-defined]
        out.append(
            (
                r.tenant_id,  # type: ignore[attr-defined]
                Finding(
                    rule_id=RULE_ID,
                    rule_name=RULE_NAME,
                    title=f"Blocked remote tool {tool.name} found on {r.hostname}",  # type: ignore[attr-defined]
                    severity="high",
                    tactic="Command and Control",
                    technique="T1219",
                    key=f"{r.tool_key}:{host_key(r.hostname)}",  # type: ignore[attr-defined]
                    occurred_at=now,
                    summary=(
                        f"{tool.name}{version} is installed on {r.hostname}, and it is marked as blocked: nobody should be running it. Remote access software is a common way for an attacker to keep a way back in, "
                        "and a forgotten technician tool is a way in too. Find out who installed it; if it is not meant to be there, remove it and check what connected through it."
                    ),
                    fields=[("Tool", tool.name), ("Device", r.hostname), ("Version", version.strip() or "unknown"), ("Kind", tool.category.replace("_", " "))],  # type: ignore[attr-defined]
                    source_ids=[],
                ),
            )
        )
    return out

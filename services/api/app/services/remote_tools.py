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
    category: str  # rmm | remote_access | remote_support | file_transfer | remote_desktop_manager | tunnel
    # Regular expressions tried against "<program name>" (and "<program name> <publisher>" where the pattern says so with \b boundaries).
    patterns: tuple[str, ...]
    # Some tools are installed once per server they connect to, and the install says which server in its name or folder (ScreenConnect: "ScreenConnect Client (798cebdb8316a8ff)"). A regular
    # expression with one group that picks that identifier out of the program name or install path; None for a tool that has no such thing.
    instance_pattern: str | None = None


CATALOG: tuple[Tool, ...] = (
    Tool(
        "acronis_remotely",
        "Acronis Cyber Protect (Remotely)",
        "remote_support",
        (r"\bacronis\b.*\b(remote|cyber protect connect|cyber protect.*agent)\b", r"\bremotely\b.*\bacronis\b"),
    ),
    Tool("anydesk", "AnyDesk", "remote_access", (r"^anydesk\b", r"\banydesk\b(?!.*manager)")),
    Tool("atera", "Atera", "rmm", (r"\batera\b.*\b(agent|networks)\b", r"^atera\b", r"\bateraagent\b")),
    Tool("aweray", "AweRay (AweSun)", "remote_access", (r"\bawesun\b", r"\baweray\b")),
    Tool(
        "beyondtrust",
        "BeyondTrust (Bomgar)",
        "remote_support",
        (r"\bbomgar\b", r"\bbeyondtrust\b.*\b(remote support|jump client|representative console|endpoint)\b"),
    ),
    Tool("chrome_remote_desktop", "Chrome Remote Desktop", "remote_access", (r"\bchrome remote desktop\b",)),
    Tool(
        "connectwise_automate",
        "ConnectWise Automate (LabTech)",
        "rmm",
        (r"\blabtech\b", r"\bconnectwise automate\b", r"\bltsvc\b", r"\bautomate agent\b"),
    ),
    Tool(
        "connectwise_rmm",
        "ConnectWise RMM",
        "rmm",
        (r"\bconnectwise rmm\b", r"\bconnectwise.*\bcontinuum\b", r"\bconnectwise manage agent\b"),
    ),
    Tool("datto_rmm", "Datto RMM", "rmm", (r"\bdatto rmm\b", r"\bdattoagent\b", r"\bcentrastage\b", r"\bdatto\b.*\bagent\b")),
    Tool(
        "devolutions_rdm",
        "Devolutions Remote Desktop Manager",
        "remote_desktop_manager",
        (r"\bremote desktop manager\b.*\bdevolutions\b", r"\bdevolutions\b.*\bremote desktop manager\b", r"^remote desktop manager\b"),
    ),
    Tool("duet_display", "Duet Display", "remote_access", (r"\bduet display\b",)),
    Tool("gotoassist", "GoToAssist", "remote_support", (r"\bgotoassist\b", r"\bgoto assist\b")),
    Tool("gotoresolve", "GoToAssist (GoTo Resolve)", "remote_support", (r"\bgoto resolve\b", r"\bgotoresolve\b")),
    Tool("gotomypc", "GoToMyPC", "remote_access", (r"\bgotomypc\b", r"\bgoto my pc\b")),
    Tool("iperius_remote", "Iperius Remote", "remote_access", (r"\biperius remote\b",)),
    Tool("jumpcloud", "JumpCloud", "rmm", (r"\bjumpcloud\b",)),
    Tool("kaseya_vsa", "Kaseya (VSA)", "rmm", (r"\bkaseya\b", r"\bkaseyad\b", r"\bkaseya agent\b")),
    Tool("logmein", "LogMeIn", "remote_access", (r"^logmein\b(?!.*rescue)", r"\blogmein pro\b", r"\blogmein hamachi\b")),
    Tool("logmein_rescue", "LogMeIn Rescue", "remote_support", (r"\blogmein rescue\b", r"\bgotoassist rescue\b")),
    Tool(
        "nable_ama",
        "N-able Advanced Monitoring Agent",
        "rmm",
        (r"\badvanced monitoring agent\b", r"\bn-able\b.*\bmonitoring\b", r"\bsolarwinds msp\b.*\bagent\b"),
    ),
    Tool(
        "nable_take_control",
        "N-able Take Control",
        "remote_support",
        (r"\btake control\b.*\b(n-able|solarwinds|mspa?)\b", r"\bbasic take control\b", r"\bbeanywhere\b"),
    ),
    Tool("ninjaone", "NinjaOne (formerly NinjaRMM)", "rmm", (r"\bninjarmm", r"\bninjaone\b", r"\bninja ?rmm agent\b")),
    Tool("pulseway", "Pulseway", "rmm", (r"\bpulseway\b",)),
    Tool("putty", "PuTTY", "remote_access", (r"^putty\b",)),
    Tool("radmin", "RAdmin", "remote_access", (r"\bradmin (server|viewer)\b", r"^radmin\b", r"\bremote administrator\b.*\bfamatech\b")),
    Tool("remotepc", "RemotePC", "remote_access", (r"^remotepc\b", r"\bremotepc (host|viewer)\b")),
    Tool(
        "screenconnect",
        "ScreenConnect",
        "remote_support",
        (r"\bscreenconnect\b", r"\bconnectwise control\b"),
        r"(?<![0-9a-f])([0-9a-f]{16})(?![0-9a-f])",
    ),
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
    # ---- more, added 2026-11-03: the tools criminals and careless technicians use most that the first list did not have
    Tool("quick_assist", "Microsoft Quick Assist", "remote_support", (r"^quick assist\b", r"\bmicrosoft quick assist\b")),
    Tool("remote_help", "Microsoft Remote Help", "remote_support", (r"^remote help\b(?!.*(nurse|doctor))", r"\bmicrosoft remote help\b")),
    Tool("rustdesk", "RustDesk", "remote_access", (r"\brustdesk\b",)),
    Tool("nomachine", "NoMachine", "remote_access", (r"\bnomachine\b",)),
    Tool("parsec", "Parsec", "remote_access", (r"^parsec\b", r"\bparsec (host|app)\b")),
    Tool("meshcentral", "MeshCentral", "rmm", (r"\bmeshcentral\b", r"\bmesh agent\b", r"\bmeshagent\b")),
    Tool("tactical_rmm", "Tactical RMM", "rmm", (r"\btactical rmm\b", r"\btacticalrmm\b", r"\btacticalagent\b")),
    Tool("action1", "Action1", "rmm", (r"\baction1\b",)),
    Tool("level", "Level", "rmm", (r"^level\b(?=.*(agent|rmm))", r"^level level\b", r"\blevel\.io\b", r"\blevel remote\b")),
    Tool(
        "manageengine_rap",
        "ManageEngine Remote Access Plus / Endpoint Central",
        "rmm",
        (
            r"\bremote access plus\b",
            r"\bendpoint central\b",
            r"\bdesktop central\b",
            r"\bmanageengine\b.*\b(agent|uems)\b",
            r"\bzoho assist\b.*\bmanageengine\b",
        ),
    ),
    Tool("dameware", "DameWare", "remote_support", (r"\bdameware\b",)),
    Tool("isl_online", "ISL Online", "remote_support", (r"\bisl (light|online|always on)\b", r"\bisl light\b")),
    Tool("supremo", "Supremo", "remote_access", (r"^supremo\b", r"\bnanosystems\b.*\bsupremo\b")),
    Tool("ultraviewer", "UltraViewer", "remote_access", (r"\bultraviewer\b",)),
    Tool("ammyy", "Ammyy Admin", "remote_access", (r"\bammyy\b",)),
    Tool("remote_utilities", "Remote Utilities", "remote_access", (r"\bremote utilities\b", r"\brutserv\b")),
    Tool("dwservice", "DWService", "remote_access", (r"\bdwservice\b", r"\bdwagent\b")),
    Tool("anyviewer", "AnyViewer", "remote_access", (r"\banyviewer\b",)),
    Tool("hoptodesk", "HopToDesk", "remote_access", (r"\bhoptodesk\b",)),
    Tool("sunlogin", "Sunlogin (Oray)", "remote_access", (r"\bsunlogin\b", r"\boray\b")),
    Tool("nable_ncentral", "N-able N-central", "rmm", (r"\bn-central\b", r"\bncentral\b", r"^windows agent\b.*\bn-able\b")),
    Tool("tailscale", "Tailscale", "tunnel", (r"^tailscale\b",)),
    Tool("zerotier", "ZeroTier", "tunnel", (r"\bzerotier\b",)),
    Tool("ngrok", "ngrok", "tunnel", (r"^ngrok\b", r"\bngrok agent\b")),
)

_BY_KEY = {t.key: t for t in CATALOG}
_COMPILED: list[tuple[Tool, list[re.Pattern[str]]]] = [(t, [re.compile(p, re.IGNORECASE) for p in t.patterns]) for t in CATALOG]


def tool_by_key(key: str) -> Tool | None:
    return _CUSTOM.get().get(key) or _BY_KEY.get(key)


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
    done: set[tuple[uuid.UUID, str]] = set()
    for r in sorted(rows, key=lambda r: (str(r.tenant_id), host_key(r.hostname), r.tool_key, getattr(r, "instance_id", "") or "")):  # type: ignore[attr-defined]
        tool = tool_by_key(r.tool_key)  # type: ignore[attr-defined]
        if tool is None or effective_verdict(r.tool_key, r.tenant_id, rules) != "blocked":  # type: ignore[attr-defined]
            continue
        once = (r.tenant_id, f"{r.tool_key}:{host_key(r.hostname)}")  # type: ignore[attr-defined]
        if once in done:
            continue  # a second install of the same tool on the same device is the same alert
        done.add(once)
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
                    fields=[
                        ("Tool", tool.name),
                        ("Device", r.hostname),
                        ("Version", version.strip() or "unknown"),
                        ("Kind", tool.category.replace("_", " ")),
                        ("Installed at", getattr(r, "install_path", None) or "unknown"),
                    ],  # type: ignore[attr-defined]
                    source_ids=[],
                ),
            )
        )
    return out


# ---- which server an install belongs to (ScreenConnect) -----------------------------------------------------------------------------------------------------

INSTANCE_ID = re.compile(r"^[0-9a-f]{8,40}$")
SETTINGS_KEY = "remote_tool_instances"


def instance_of(tool_key: str, *texts: str | None) -> str:
    """The identifier of the server an install belongs to, from its program name or install path (the first text that has one), lower case; '' when the tool has no such thing or none is found."""
    tool = tool_by_key(tool_key)
    if tool is None or tool.instance_pattern is None:
        return ""
    pattern = re.compile(tool.instance_pattern, re.IGNORECASE)
    for text in texts:
        m = pattern.search(text or "")
        if m:
            return m.group(1).lower()
    return ""


def normalize_instance_ids(ids: Iterable[str]) -> list[str]:
    """A list as it is stored: trimmed, lower case, unique, sorted. Raises ValueError naming the first that is not a hexadecimal identifier of 8 to 40 characters."""
    seen: set[str] = set()
    for raw in ids:
        v = (raw or "").strip().lower()
        if not INSTANCE_ID.match(v):
            raise ValueError(v or "(empty)")
        seen.add(v)
    return sorted(seen)


def trusted_instances(settings: object) -> dict[str, list[str]]:
    """The server identifiers the owner says are theirs, per tool, from the managing company's settings. Anything malformed is ignored."""
    raw = (settings or {}).get(SETTINGS_KEY) if isinstance(settings, dict) else None
    out: dict[str, list[str]] = {}
    if isinstance(raw, dict):
        for key, ids in raw.items():
            if key in _BY_KEY and isinstance(ids, list):
                good = [i for i in ids if isinstance(i, str) and INSTANCE_ID.match(i)]
                if good:
                    out[key] = sorted(set(good))
    return out


def with_trusted_instances(settings: object, tool_key: str, ids: list[str]) -> dict[str, object]:
    """A copy of the settings with one tool's identifiers set (the entry is removed when the list is empty)."""
    out = dict(settings or {}) if isinstance(settings, dict) else {}
    current = dict(trusted_instances(settings))
    chosen = normalize_instance_ids(ids)
    if chosen:
        current[tool_key] = chosen
    else:
        current.pop(tool_key, None)
    if current:
        out[SETTINGS_KEY] = current
    else:
        out.pop(SETTINGS_KEY, None)
    return out


FOREIGN_RULE_ID = "aisoc-remote-tool-foreign-instance"
FOREIGN_RULE_NAME = "Remote tool connected to someone else's server"


def foreign_findings(rows: Iterable[object], trusted: dict[str, list[str]], now) -> list[tuple[uuid.UUID, object]]:
    """A critical finding for each install of a tool that belongs to a server other than the owner's (``rows``: sightings with ``tenant_id``, ``hostname``, ``tool_key``, ``instance_id``, ``install_path``).
    Only judged for a tool whose owner identifiers are known: with none set there is nothing to compare against, and nothing is raised. An install whose identifier could not be read is not judged either."""
    from app.services.identity_detections import Finding  # noqa: PLC0415

    out: list[tuple[uuid.UUID, object]] = []
    for r in sorted(rows, key=lambda r: (str(r.tenant_id), host_key(r.hostname), r.tool_key, getattr(r, "instance_id", "") or "")):  # type: ignore[attr-defined]
        mine = trusted.get(r.tool_key)  # type: ignore[attr-defined]
        tool = tool_by_key(r.tool_key)  # type: ignore[attr-defined]
        instance = getattr(r, "instance_id", "") or ""
        if not mine or tool is None or not instance or instance in mine:
            continue
        path = getattr(r, "install_path", None) or "unknown"
        out.append(
            (
                r.tenant_id,  # type: ignore[attr-defined]
                Finding(
                    rule_id=FOREIGN_RULE_ID,
                    rule_name=FOREIGN_RULE_NAME,
                    title=f"{tool.name} for another server ({instance}) found on {r.hostname}",  # type: ignore[attr-defined]
                    severity="critical",
                    tactic="Command and Control",
                    technique="T1219",
                    key=f"{r.tool_key}:{host_key(r.hostname)}:{instance}",  # type: ignore[attr-defined]
                    occurred_at=now,
                    summary=(
                        f"{tool.name} is installed on {r.hostname} and it connects to a server whose identifier is {instance}, which is not one of yours ({', '.join(mine)}). Someone with access to that other "
                        "server can control this computer. This is how attackers use a legitimate remote support tool to stay in a network (and how a technician's old or personal install is left behind). "
                        "Find out who installed it; if it is not meant to be there, remove it and treat the computer as possibly accessed."
                    ),
                    fields=[
                        ("Tool", tool.name),
                        ("Device", r.hostname),
                        ("Server identifier", instance),
                        ("Your identifiers", ", ".join(mine)),
                        ("Installed at", path),
                    ],  # type: ignore[attr-defined]
                    source_ids=[],
                ),
            )
        )
    return out


# ---- tools the owner adds by hand ----------------------------------------------------------------------------------------------------------------------------

import contextvars  # noqa: E402

CATEGORIES = ("rmm", "remote_access", "remote_support", "file_transfer", "remote_desktop_manager", "tunnel")
MAX_CUSTOM = 100

# The owner's own tools for the request being handled. A context variable, not a global: each request (each owner) sees only its own, and two requests at once never see each other's.
_CUSTOM: contextvars.ContextVar[dict[str, Tool]] = contextvars.ContextVar("remote_tool_custom", default={})


def set_custom(tools: Iterable[Tool]) -> None:
    """Make these the owner's own tools for the rest of this request."""
    _CUSTOM.set({t.key: t for t in tools})


def custom_tools() -> list[Tool]:
    return sorted(_CUSTOM.get().values(), key=lambda t: t.name.lower())


def slug_key(name: str) -> str:
    """The key a tool added by hand is stored under: ``custom_`` and the name in lower case with anything else turned into underscores."""
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")[:50]
    return f"custom_{slug}" if slug else ""


def _phrase(text: str) -> str:
    """A piece of a program name as a pattern: whole words, any amount of white space between them, no special meaning for any character the person typed."""
    words = [re.escape(w) for w in text.split()]
    body = r"\s+".join(words)
    start = r"\b" if text[:1].isalnum() else ""
    end = r"\b" if text[-1:].isalnum() else ""
    return f"{start}{body}{end}"


def build_custom(key: str, name: str, category: str, match: str, publisher: str | None) -> Tool:
    pattern = _phrase(match)
    if publisher:
        pattern = f"{pattern}(?=.*{_phrase(publisher)})"  # the publisher is only part of the text tried when the device lists one
    return Tool(key, name, category, (pattern,))


def validate_custom(name: str, category: str, match: str, publisher: str | None = None) -> tuple[str, str, str, str | None]:
    """The cleaned fields of a tool to add, or ValueError saying what is wrong and what to do about it (the message is shown to the person)."""
    name = " ".join((name or "").split())
    match = " ".join((match or "").split())
    publisher = " ".join((publisher or "").split()) or None
    if not 2 <= len(name) <= 120:
        raise ValueError("Give the tool a name of 2 to 120 characters.")
    if category not in CATEGORIES:
        raise ValueError("Pick what kind of tool it is.")
    if not 3 <= len(match) <= 80:
        raise ValueError("Give 3 to 80 characters of the program's name as the device lists it (the same as in Programs and Features).")
    if publisher is not None and not 2 <= len(publisher) <= 80:
        raise ValueError("The publisher, when given, is 2 to 80 characters.")
    if len(match.split()) == 1 and len(match) < 4:
        raise ValueError("That is too short to be specific: it would match unrelated programs. Use more of the name.")
    return name, category, match, publisher


def covered_by_builtin(match: str) -> Tool | None:
    """The built-in tool that already recognises a program with this name, if any (so the same program is not added twice)."""
    for tool, patterns in _COMPILED:
        if any(p.search(match) for p in patterns):
            return tool
    return None

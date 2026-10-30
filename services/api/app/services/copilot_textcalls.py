"""Tool calls a model wrote as TEXT, for the models behind the gateway that cannot call tools natively.

Such a model answers a question that needs a tool with a block like

    ```tool_use
    search_halo_guides
    {"query": "recurring invoices"}
    ```

which the analyst used to see as the answer. ``parse_text_tool_calls`` finds those blocks so the chat can run the tool and give the model the result. Only read-only tools are accepted from text: a tool that changes
or deletes something is reached only through the model's real tool call, where the analyst's confirmation applies.
"""

from __future__ import annotations

import json
import re
from typing import Any

# The tools a text-written call may run: all read-only.
TEXT_CALLABLE: frozenset[str] = frozenset(
    {
        "search_alerts",
        "search_cases",
        "get_alert",
        "search_client_docs",
        "search_halo_guides",
        "read_halo_guide",
        "client_checks",
        "client_changes",
        "client_overview",
        "related_alerts",
        "secureframe_status",
    }
)
MAX_TEXT_CALLS = 3
_BLOCK = re.compile(r"```\s*(?:tool_use|tool_call|tool)\s*\n\s*([A-Za-z_][A-Za-z0-9_]*)\s*\n(.*?)```", re.DOTALL)
# The XML style some models write instead: <function_calls><invoke name="client_changes"><parameter name="client">Acme</parameter></invoke></function_calls>
_XML_BLOCK = re.compile(r"<function_calls>.*?</function_calls>|<invoke\s+name=.*?</invoke>", re.DOTALL | re.IGNORECASE)
_XML_INVOKE = re.compile(r"<invoke\s+name=[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']\s*>(.*?)</invoke>", re.DOTALL | re.IGNORECASE)
_XML_PARAM = re.compile(r"<parameter\s+name=[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']\s*>(.*?)</parameter>", re.DOTALL | re.IGNORECASE)
_BARE = re.compile(r"^\s*<?(?:tool_use|tool_call)>?\s*\n\s*([A-Za-z_][A-Za-z0-9_]*)\s*\n(\{.*\})\s*$", re.DOTALL)


def _xml_value(raw: str) -> Any:
    """A parameter written as text: a number or true/false when it reads as one, otherwise the trimmed text."""
    text = raw.strip()
    try:
        value = json.loads(text)
    except ValueError:
        return text
    return value if isinstance(value, bool | int | float) else text


def _xml_calls(content: str) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for m in _XML_INVOKE.finditer(content or ""):
        params = {p.group(1): _xml_value(p.group(2)) for p in _XML_PARAM.finditer(m.group(2))}
        out.append((m.group(1), params))
    return out


def strip_text_tool_calls(content: str) -> str:
    """``content`` without any tool call a model wrote as text (a ```tool_use block or an XML ``function_calls`` block), so the analyst never reads one as the answer."""
    cleaned = _XML_BLOCK.sub("", content or "")
    cleaned = _BLOCK.sub("", cleaned)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def parse_text_tool_calls(content: str) -> list[tuple[str, dict[str, Any]]]:
    """``[(tool name, arguments)]`` for each read-only tool call written into ``content``, at most ``MAX_TEXT_CALLS``. A block that is not valid JSON, or names another tool, is ignored. The same call written
    twice runs once."""
    xml = [c for c in _xml_calls(content) if c[0] in TEXT_CALLABLE]
    if xml:
        unique: list[tuple[str, dict[str, Any]]] = []
        for call in xml:
            if call not in unique:
                unique.append(call)
        return unique[:MAX_TEXT_CALLS]
    found: list[tuple[str, str]] = [(m.group(1), m.group(2)) for m in _BLOCK.finditer(content or "")]
    if not found:
        bare = _BARE.match(content or "")
        if bare:
            found = [(bare.group(1), bare.group(2))]
    out: list[tuple[str, dict[str, Any]]] = []
    for name, raw in found:
        if name not in TEXT_CALLABLE:
            continue
        try:
            args = json.loads(raw.strip() or "{}")
        except ValueError:
            continue
        if isinstance(args, dict):
            out.append((name, args))
        if len(out) >= MAX_TEXT_CALLS:
            break
    return out

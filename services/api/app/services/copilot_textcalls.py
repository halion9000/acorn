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
    {"search_alerts", "search_cases", "get_alert", "search_client_docs", "search_halo_guides", "read_halo_guide"}
)
MAX_TEXT_CALLS = 3
_BLOCK = re.compile(r"```\s*(?:tool_use|tool_call|tool)\s*\n\s*([A-Za-z_][A-Za-z0-9_]*)\s*\n(.*?)```", re.DOTALL)
_BARE = re.compile(r"^\s*<?(?:tool_use|tool_call)>?\s*\n\s*([A-Za-z_][A-Za-z0-9_]*)\s*\n(\{.*\})\s*$", re.DOTALL)


def parse_text_tool_calls(content: str) -> list[tuple[str, dict[str, Any]]]:
    """``[(tool name, arguments)]`` for each read-only tool call written into ``content``, at most ``MAX_TEXT_CALLS``. A block that is not valid JSON, or names another tool, is ignored."""
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

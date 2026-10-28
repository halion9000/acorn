"""Which ATT&CK tactic a technique belongs to, so a rule that names techniques but no tactics (which is how every shipped rule is written) can still be placed on the coverage heatmap.

The data is ``mitre_tactics.json``: the primary tactic of each technique and sub-technique id, taken from MITRE ATT&CK Enterprise v20.0 (the earliest of its tactics in kill-chain order, so a
technique that spans several is placed once, the same way every time). Revoked ids are kept, so rules written against an older id (T1562.001 is now T1685) still place. MITRE ATT&CK(R) is
(c) The MITRE Corporation, used under the ATT&CK Terms of Use.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_FILE = Path(__file__).with_name("mitre_tactics.json")


@lru_cache(maxsize=1)
def _data() -> dict[str, Any]:
    return json.loads(_FILE.read_text(encoding="utf-8"))


def tactic_of(technique_id: str | None) -> str | None:
    """The display name of the technique's tactic ("Credential Access"), or None when the id is not an ATT&CK enterprise technique (a mobile one, a typo)."""
    tid = str(technique_id or "").strip().upper()
    data = _data()
    key = tid if tid in data["techniques"] else tid.split(".")[0]
    short = data["techniques"].get(key)
    return data["tactic_names"].get(short) if short else None


def tactic_rank(name: str) -> int:
    """Where a tactic name sits in kill-chain order (unknown names last), for listing columns the way ATT&CK does."""
    data = _data()
    names = [data["tactic_names"][short] for short in data["tactic_order"]]
    return names.index(name) if name in names else len(names)

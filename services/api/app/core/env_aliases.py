"""The A.C.O.R.N name for environment settings, with the old AISOC_ name still honored.

``ACORN_X`` is copied to ``AISOC_X`` before settings are read, so a machine can move its ``.env`` to the new names one setting at a time and nothing changes until it does. The new name wins over the old
one; a blank new value never hides a real old one; a setting set both ways to different values is reported (never the values). Only names that start with ``ACORN_`` are touched, and the process
environment is the only thing changed (no file is written).
"""

from __future__ import annotations

import logging
import os
from collections.abc import MutableMapping

log = logging.getLogger(__name__)

NEW_PREFIX = "ACORN_"
OLD_PREFIX = "AISOC_"


def apply_acorn_aliases(environ: MutableMapping[str, str] | None = None) -> list[str]:
    """Copy each ``ACORN_X`` to ``AISOC_X``. Returns the names (without prefix) that were set both ways to different values, for a log line; the new value is used."""
    env = os.environ if environ is None else environ
    clashes: list[str] = []
    for key in [k for k in env if k.startswith(NEW_PREFIX)]:
        name = key[len(NEW_PREFIX) :]
        fresh = (env.get(key) or "").strip()
        if not name or not fresh:
            continue
        old_key = OLD_PREFIX + name
        old = (env.get(old_key) or "").strip()
        if old and old != fresh:
            clashes.append(name)
        env[old_key] = fresh
    if clashes:
        log.warning("Both ACORN_ and AISOC_ are set to different values for: %s. The ACORN_ value is used.", ", ".join(sorted(clashes)))
    return sorted(clashes)

"""One-off: say A.C.O.R.N instead of AiSOC in prose (docstrings, comments, descriptions, messages, emails). Dry run unless --write.

Left alone on purpose: anything that is a name rather than a word: paths and URLs (a / next to it), repo and folder names ("AiSOC repo", "AiSOC fork", "AiSOC checkout"), headers (X-AiSOC-*), env vars
(AISOC_*), identifiers (aisoc_*, AiSOC_Alerts), the demo-mode page that credits the upstream project, vendored upstream code and the marketing pages' credit to the original project.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRITE = "--write" in sys.argv
TARGETS = [ROOT / "services" / "api" / "app", ROOT / "docs"]
SKIP_PARTS = {"node_modules", ".venv", "__pycache__", "tests", "test", "data", "_vendor", "migrations", "fixtures", "review"}
# docs/api and docs/openapi.yaml are generated from the code; they are regenerated, never edited. services/api/app/api is the code's own "api" package, so it is let through below.
SKIP_FILES = {"demo_mode.py", "demo_seed.py"}
SUFFIXES = {".py", ".ts", ".tsx", ".md", ".yaml", ".yml", ".txt"}
# "AiSOC's" and "AiSOC." at a sentence end are prose; "AiSOC.x" or "AiSOC_x" are names (the lookahead above lets a trailing . or 's through only when nothing word-like follows).
PATTERN = re.compile(r"(?<![/\w.\-#@:])AiSOC(?=(?:'s|’s)?(?:[\s,.;:)\"'\]`*!?]|$))(?! (?:repo|repository|fork|folder|checkout)\b)")

changed = 0
hits = 0
for base in TARGETS:
    for path in base.rglob("*"):
        if not path.is_file() or path.suffix not in SUFFIXES or path.name in SKIP_FILES:
            continue
        rel = path.relative_to(ROOT)
        if SKIP_PARTS & set(rel.parts) or rel.parts[:2] == ("docs", "api") or path.name == "openapi.yaml":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        new, n = PATTERN.subn("A.C.O.R.N", text)
        if n:
            hits += n
            changed += 1
            if WRITE:
                path.write_text(new, encoding="utf-8", newline="")
print(f"{'wrote' if WRITE else 'would change'} {hits} mentions in {changed} files{'' if WRITE else ' (dry run; pass --write)'}")

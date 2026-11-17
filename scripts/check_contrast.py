#!/usr/bin/env python3
"""Check text contrast in both themes (roadmap r7-ai-16).

Reads the colour tokens of ``apps/web/src/app/globals.css`` (the dark theme in ``:root, [data-theme="dark"]``, the light theme in ``[data-theme="light"]``) and measures the WCAG 2 contrast ratio
of every text colour against every surface colour it sits on. Body text (primary, secondary, muted) needs 4.5:1; the "subtle" colour is for timestamps and helper text and needs 3:1.

    python scripts/check_contrast.py            prints every pair and exits 1 when one is under its minimum
    python scripts/check_contrast.py --list     prints every pair and always exits 0

Only solid ``#rrggbb`` tokens are measured; a token that is not (a gradient, an rgba border) is not a text or surface colour. jsdom has no styles, so this is the only contrast check there is.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CSS = Path(__file__).resolve().parents[1] / "apps" / "web" / "src" / "app" / "globals.css"
TEXT_MIN = {"fg-primary": 4.5, "fg-secondary": 4.5, "fg-muted": 4.5, "fg-subtle": 3.0}
SURFACES = ("surface-base", "surface-raised", "surface-card", "surface-hover", "surface-subtle")


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = value.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def luminance(rgb: tuple[int, int, int]) -> float:
    def channel(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """The WCAG 2 contrast ratio of two #rrggbb colours (1 to 21)."""
    la, lb = luminance(hex_to_rgb(a)), luminance(hex_to_rgb(b))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def tokens(block: str) -> dict[str, str]:
    """The solid #rrggbb custom properties of one CSS block, by name without the leading dashes."""
    return {m.group(1): m.group(2) for m in re.finditer(r"--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{3,6})\b", block)}


def theme_blocks(css: str) -> dict[str, str]:
    """The text of the dark theme block and of the light theme block."""
    out: dict[str, str] = {}
    for name, selector in (("dark", r':root,\s*\[data-theme="dark"\]'), ("light", r'\[data-theme="light"\]')):
        m = re.search(selector + r"\s*\{(.*?)\n\}", css, re.S)
        if m and name not in out:
            out[name] = m.group(1)
    return out


def check(css: str) -> list[tuple[str, str, str, float, float]]:
    """Every (theme, text token, surface token, ratio, minimum), the failures first."""
    rows: list[tuple[str, str, str, float, float]] = []
    for theme, block in theme_blocks(css).items():
        t = tokens(block)
        for fg, minimum in TEXT_MIN.items():
            for surface in SURFACES:
                if fg in t and surface in t:
                    rows.append((theme, fg, surface, round(contrast(t[fg], t[surface]), 2), minimum))
    return sorted(rows, key=lambda r: (r[3] >= r[4], r[0], r[1], r[2]))


def main(argv: list[str]) -> int:
    rows = check(CSS.read_text(encoding="utf-8"))
    if not rows:
        print("check_contrast: no colour tokens found in globals.css")
        return 1
    failures = [r for r in rows if r[3] < r[4]]
    for theme, fg, surface, ratio, minimum in rows:
        print(f"{'FAIL' if ratio < minimum else 'ok  '} {theme:5} {fg:13} on {surface:15} {ratio:5.2f}:1 (needs {minimum})")
    print(f"{len(failures)} of {len(rows)} pairs under their minimum")
    return 0 if "--list" in argv else (1 if failures else 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""The contrast checker (scripts/check_contrast.py): its arithmetic is right, and both themes of the console meet their minimums."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check_contrast.py"
spec = importlib.util.spec_from_file_location("check_contrast", SCRIPT)
cc = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
spec.loader.exec_module(cc)  # type: ignore[union-attr]


def test_the_ratio_matches_the_wcag_reference_values():
    assert round(cc.contrast("#000000", "#ffffff"), 2) == 21.0
    assert round(cc.contrast("#ffffff", "#ffffff"), 2) == 1.0
    assert round(cc.contrast("#777777", "#ffffff"), 2) == 4.48  # the well known "just under 4.5" grey
    assert cc.contrast("#123456", "#fedcba") == cc.contrast("#fedcba", "#123456")
    assert cc.hex_to_rgb("#abc") == (170, 187, 204)


def test_a_failing_pair_is_reported_first_and_a_non_colour_token_is_ignored():
    css = """
:root, [data-theme="dark"] {
  --surface-base: #000000;
  --fg-primary: #111111;
  --fg-secondary: #ffffff;
  --surface-border: rgba(1, 2, 3, 0.1);
}
[data-theme="light"] {
  --surface-base: #ffffff;
  --fg-primary: #000000;
}
"""
    rows = cc.check(css)
    assert [(r[0], r[1]) for r in rows] == [("dark", "fg-primary"), ("dark", "fg-secondary"), ("light", "fg-primary")]
    assert rows[0][3] < rows[0][4] <= rows[1][4] <= rows[1][3], "the failure comes first, then the passes"


def test_the_consoles_two_themes_meet_the_contrast_minimums():
    rows = cc.check(cc.CSS.read_text(encoding="utf-8"))
    assert {r[0] for r in rows} == {"dark", "light"}
    assert len(rows) >= 36
    assert [r for r in rows if r[3] < r[4]] == []

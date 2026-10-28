"""The Detection Catalog is filled from the Sigma rules the repository ships."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from app.scripts import load_catalog_detections as lc
from app.scripts.load_builtin_detections import detections_dir

RULE = """id: sigmahq-sigma-1
name: AWS EC2 Disable EBS Encryption
description: Identifies disabling of default encryption.
severity: medium
tags:
  mitre:
  - T1486
  categories:
  - cloud
logsource:
  product: aws
  service: cloudtrail
detection:
  selection:
    eventName: DisableEbsEncryptionByDefault
  condition: selection
provenance:
  source: SigmaHQ/sigma
  license: DRL-1.1
  license_url: https://github.com/SigmaHQ/Detection-Rule-License
"""

NOW = "2026-10-28T00:00:00+00:00"


def tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = tmp_path / lc.SOURCE_DIR / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def test_a_rule_becomes_an_approved_entry_the_catalog_page_and_install_can_use():
    e = lc.entry_for(RULE, "detections/sigma-imports/cloud/x.yaml", NOW)
    assert e["status"] == "approved"
    assert (e["id"], e["name"], e["level"]) == ("sigmahq-sigma-1", "AWS EC2 Disable EBS Encryption", "medium")
    assert (e["logsource_product"], e["logsource_category"]) == ("aws", "")
    assert e["tags"] == ["attack.t1486", "cloud"]
    assert "DRL-1.1" in e["author"]
    assert e["sigma_yaml"] == RULE  # what Install copies into the tenant's rules, unchanged
    assert (e["install_count"], e["rating_count"]) == (0, 0)


def test_files_that_are_not_rules_are_left_out():
    for text in (
        "",
        "- a list",
        "id: x\nname: y\n",
        "id: 1\nname: n\nlogsource: {product: a}\n",
        ":\n  - [",
        "id: ''\nname: n\nlogsource: {}\ndetection: {a: 1}\n",
    ):
        assert lc.entry_for(text, "f.yaml", NOW) is None


def test_an_unknown_level_is_medium():
    assert lc.entry_for(RULE.replace("severity: medium", "severity: spicy"), "f", NOW)["level"] == "medium"


def test_quarantined_rules_and_duplicates_are_not_listed(tmp_path):
    root = tree(
        tmp_path,
        {
            "cloud/a.yaml": RULE,
            "cloud/dup.yaml": RULE,
            "_quarantine/cloud/q.yaml": RULE.replace("sigmahq-sigma-1", "sigmahq-sigma-2"),
            "endpoint/bad.yaml": "not: a rule",
        },
    )
    entries, skipped = lc.read_entries(root, NOW)
    assert [e["id"] for e in entries] == ["sigmahq-sigma-1"]
    assert len(skipped) == 2


def test_a_missing_folder_lists_nothing(tmp_path):
    assert lc.read_entries(tmp_path, NOW) == ([], [])


class FakeSession:
    def __init__(self, have):
        self.have = have
        self.added = []

    async def execute(self, _stmt):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: list(self.have)))

    def add(self, row):
        self.added.append(row)


def test_load_adds_only_what_the_catalog_lacks_and_never_touches_existing_entries():
    es = [lc.entry_for(RULE.replace("sigmahq-sigma-1", f"r{i}"), "f", NOW) for i in range(3)]
    s = FakeSession(have={"r1"})
    out = asyncio.run(lc.load(s, es))
    assert out == {"created": 2, "existing": 1}
    assert sorted(r.item_id for r in s.added) == ["r0", "r2"]
    assert all((r.kind, r.status) == ("detection", "approved") for r in s.added)


def test_the_shipped_folder_yields_a_real_catalog():
    root = detections_dir()
    assert root is not None
    entries, _ = lc.read_entries(root, NOW)
    assert len(entries) >= 50
    assert len({e["id"] for e in entries}) == len(entries)
    assert all(e["sigma_yaml"] and e["name"] for e in entries)

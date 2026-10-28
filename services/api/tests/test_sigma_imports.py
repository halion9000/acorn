"""The imported Sigma rules the repository ships are read as plain entries (they become the parent's rules and rule packs)."""

from __future__ import annotations

from pathlib import Path

from app.scripts.load_builtin_detections import detections_dir
from app.services import sigma_imports as si

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


def tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = tmp_path / si.SOURCE_DIR / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def test_a_rule_becomes_an_entry_with_its_name_level_tags_logsource_and_licence():
    e = si.entry_for(RULE, "sigma-imports/cloud/x.yaml")
    assert (e["id"], e["name"], e["level"]) == ("sigmahq-sigma-1", "AWS EC2 Disable EBS Encryption", "medium")
    assert (e["logsource_product"], e["logsource_category"]) == ("aws", "")
    assert e["tags"] == ["attack.t1486", "cloud"]
    assert "DRL-1.1" in e["author"] and e["license_url"] == "https://github.com/SigmaHQ/Detection-Rule-License"
    assert e["sigma_yaml"] == RULE  # the rule text, unchanged
    assert e["source_file"] == "sigma-imports/cloud/x.yaml"


def test_files_that_are_not_rules_are_left_out():
    for text in (
        "",
        "- a list",
        "id: x\nname: y\n",
        "id: 1\nname: n\nlogsource: {product: a}\n",
        ":\n  - [",
        "id: ''\nname: n\nlogsource: {}\ndetection: {a: 1}\n",
    ):
        assert si.entry_for(text, "f.yaml") is None


def test_an_unknown_level_is_medium():
    assert si.entry_for(RULE.replace("severity: medium", "severity: spicy"), "f")["level"] == "medium"


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
    entries, skipped = si.read_entries(root)
    assert [e["id"] for e in entries] == ["sigmahq-sigma-1"]
    assert len(skipped) == 2


def test_a_missing_folder_lists_nothing(tmp_path):
    assert si.read_entries(tmp_path) == ([], [])


def test_the_shipped_folder_yields_a_real_set_of_rules():
    root = detections_dir()
    assert root is not None
    entries, _ = si.read_entries(root)
    assert len(entries) >= 50
    assert len({e["id"] for e in entries}) == len(entries)
    assert all(e["sigma_yaml"] and e["name"] for e in entries)

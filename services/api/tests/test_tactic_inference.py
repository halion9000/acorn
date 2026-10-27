"""An alert whose source named no ATT&CK tactic gets the one its title clearly belongs to, and nothing when no rule fits."""

from __future__ import annotations

import pytest
from app.services.tactic_inference import infer_tactic, tactics_for


@pytest.mark.parametrize(
    ("title", "tactic"),
    [
        ("Microsoft 365: User Authentication from New Country", "Initial Access"),
        ("Potential Unsecured Credentials in Files", "Credential Access"),
        ("Microsoft 365: Sharepoint 100 or more file deletions in 15 minutes", "Impact"),
        ("BitLocker encryption is disabled for disk volume: 'C:'", "Defense Evasion"),
        ("The following software : *Huntress* was not installed", "Defense Evasion"),
        ("A flood of dynamic DNS updates may cause named to allocate large amounts of memory", "Impact"),
        ("Heap buffer overflow in libwebp allowed a remote attacker to perform an out of bounds memory write", "Execution"),
    ],
)
def test_clear_titles_get_their_tactic(title, tactic):
    assert infer_tactic(title) == tactic


@pytest.mark.parametrize("title", ["Process: 'com.huntress.HuntressAgent' does not exist", "C:", "HTTP is running on tcp Port 80.", "", None])
def test_a_title_no_rule_fits_gets_no_tactic(title):
    assert infer_tactic(title) is None


def test_a_tactic_the_source_named_always_wins():
    assert tactics_for(["Discovery"], "ransomware detected") == ["Discovery"]
    assert tactics_for([], "ransomware detected") == ["Impact"]
    assert tactics_for(None, "nothing to see") == []

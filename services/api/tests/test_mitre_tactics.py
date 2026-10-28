"""Which tactic an ATT&CK technique belongs to."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.mitre_tactics import tactic_of, tactic_rank

DATA = json.loads((Path(__file__).resolve().parents[1] / "app" / "services" / "mitre_tactics.json").read_text(encoding="utf-8"))


def test_a_technique_and_its_sub_techniques_have_the_tactic_attack_gives_them():
    assert tactic_of("T1190") == "Initial Access"
    assert tactic_of("T1003") == tactic_of("T1003.001") == "Credential Access"
    assert tactic_of("t1078.004") == "Initial Access", "case does not matter"
    assert tactic_of(" T1486 ") == "Impact"


def test_an_id_that_is_not_an_enterprise_technique_has_no_tactic():
    for bad in (None, "", "T9999", "not-an-id", "T1404"):
        assert tactic_of(bad) is None, bad


def test_an_older_id_that_attack_replaced_still_places():
    # T1562.001 ("Disable or Modify Tools") is now T1685; rules written against the old id keep their place.
    assert tactic_of("T1562.001") is not None


def test_tactics_are_listed_in_kill_chain_order_and_unknown_ones_last():
    names = [DATA["tactic_names"][s] for s in DATA["tactic_order"]]
    assert [tactic_rank(n) for n in names] == list(range(len(names)))
    assert tactic_rank("Initial Access") < tactic_rank("Execution") < tactic_rank("Impact") < tactic_rank("not a tactic")


def test_every_technique_points_at_a_tactic_that_exists():
    assert len(DATA["techniques"]) > 500
    assert set(DATA["techniques"].values()) <= set(DATA["tactic_order"])

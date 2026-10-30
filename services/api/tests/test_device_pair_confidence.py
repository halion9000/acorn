"""How sure A.C.O.R.N is that two devices are one machine, and why, for the person who decides on a merge."""

from types import SimpleNamespace

from app.services.device_identity import confidence_label, pair_confidence


def dev(hostname, serial=None, ips=(), maker=None):
    return SimpleNamespace(hostname=hostname, serial_number=serial, ip_addresses=list(ips), manufacturer=maker)


def test_the_same_name_address_and_maker_is_high_confidence_with_every_reason_given():
    score, why = pair_confidence(dev("PC-01.corp.local", ips=["10.0.0.5"], maker="Dell Inc."), dev("pc-01", ips=["10.0.0.5"], maker="dell"))
    assert score == 75 and confidence_label(score) == "high"
    assert why == ["same name", "shares the address 10.0.0.5", "same maker"]


def test_a_name_that_differs_only_in_punctuation_or_a_suffix_scores_below_an_identical_name():
    exact, _ = pair_confidence(dev("Front-Desk"), dev("front-desk"))
    loose, why = pair_confidence(dev("Front Desk"), dev("Front-Desk (1)"))
    assert loose < exact and "apart from punctuation" in why[0]


def test_a_name_cut_to_fifteen_characters_is_recognised():
    score, why = pair_confidence(dev("ACCOUNTING-LAPTOP-07"), dev("ACCOUNTING-LAPT"))
    assert score == 30 and "NetBIOS" in why[0]
    assert pair_confidence(dev("short"), dev("shortened-name"))[0] == 0


def test_two_different_serials_rule_the_pair_out_and_the_same_serial_makes_it_near_certain():
    score, why = pair_confidence(dev("pc-02", serial="ABC12345"), dev("pc-02", serial="XYZ98765"))
    assert score == 0 and "different serial numbers" in why
    score, why = pair_confidence(dev("pc-02", serial="ABC12345"), dev("pc-02", serial="abc12345"))
    assert score == 95 and "same serial number" in why


def test_different_makers_count_against_a_pair_and_the_score_stays_between_0_and_100():
    score, why = pair_confidence(dev("pc-03", maker="Dell"), dev("pc-03", maker="Apple"))
    assert score == 15 and "different makers" in why
    top, _ = pair_confidence(
        dev("pc-04", serial="SER-0001", ips=["10.1.1.1"], maker="HP"), dev("pc-04", serial="SER-0001", ips=["10.1.1.1"], maker="HP")
    )
    assert top == 100


def test_a_pair_with_nothing_in_common_scores_zero_and_the_labels_have_their_bands():
    assert pair_confidence(dev("alpha"), dev("omega")) == (0, [])
    assert [confidence_label(n) for n in (0, 39, 40, 69, 70, 100)] == ["low", "low", "medium", "medium", "high", "high"]

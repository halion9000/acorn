from app.services.client_matching import Candidate, is_confident, normalize_name, score, suggest

TENANTS = [
    Candidate("t1", "Acme Dental"),
    Candidate("t2", "Sportsmans Finest LLC"),
    Candidate("t3", "Legendairy Milk"),
    Candidate("t4", "Oak & Pine Realty"),
]


def test_normalize_drops_company_words_punctuation_case_and_accents():
    assert normalize_name("ACME Dental, L.L.C.") == "acme dental"
    assert normalize_name("The Café Müller Inc.") == "cafe muller"
    assert normalize_name("Oak & Pine Realty") == normalize_name("Oak and Pine Realty")
    assert normalize_name("Sportsman's Finest") == "sportsmans finest"
    assert normalize_name("  ") == ""


def test_the_same_customer_spelled_differently_is_an_exact_match():
    for spelling in ("Acme Dental, LLC", "ACME DENTAL", "acme-dental inc"):
        top = suggest(spelling, TENANTS)[0]
        assert (top.tenant_id, top.score) == ("t1", 1.0), spelling
    assert is_confident(suggest("Acme Dental, LLC", TENANTS))


def test_a_name_that_contains_the_other_is_suggested_but_not_confident():
    s = suggest("Sportsmans Finest Outfitters", TENANTS)
    assert s[0].tenant_id == "t2" and 0.6 <= s[0].score < 1.0
    assert not is_confident(s)


def test_unrelated_names_get_no_suggestion():
    assert suggest("Zenith Plumbing", TENANTS) == []
    assert score("", "Acme") == 0.0


def test_a_near_misspelling_ranks_the_right_tenant_first():
    assert suggest("Legendary Milk", TENANTS)[0].tenant_id == "t3"


def test_two_tenants_with_the_same_normalized_name_are_never_confident():
    twins = [Candidate("a", "Acme Dental LLC"), Candidate("b", "Acme Dental Inc")]
    s = suggest("Acme Dental", twins)
    assert [x.score for x in s] == [1.0, 1.0]
    assert not is_confident(s)


def test_the_shortcut_in_score_gives_exactly_the_slow_answer():
    """score() skips the slow similarity ratio when a cheap bound says it cannot matter; the answer must not change."""
    import random
    from difflib import SequenceMatcher

    from app.services.client_matching import EXACT, normalize_name, score

    def slow(a, b):
        na, nb = normalize_name(a), normalize_name(b)
        if not na or not nb:
            return 0.0
        if na == nb:
            return EXACT
        ta, tb = set(na.split()), set(nb.split())
        if ta <= tb or tb <= ta:
            return 0.85 if min(len(ta), len(tb)) >= 1 and len(na) >= 3 and len(nb) >= 3 else 0.0
        return round(max(len(ta & tb) / len(ta | tb), SequenceMatcher(None, na, nb).ratio() * 0.9), 4)

    words = ["acme", "dental", "group", "oak", "harbor", "legal", "bay", "city", "partners", "hotel", "fidelity", "revival", "medical", "llc", "inc", "co"]
    rnd = random.Random(7)
    names = [" ".join(rnd.choice(words) for _ in range(rnd.randint(1, 4))) for _ in range(150)]
    for a in names:
        for b in names[:40]:
            assert score(a, b) == slow(a, b), (a, b)


def test_a_floor_changes_nothing_at_or_above_it():
    import random
    from difflib import SequenceMatcher

    from app.services.client_matching import EXACT, normalize_name, score

    words = ["acme", "dental", "group", "oak", "harbor", "legal", "bay", "city", "partners", "hotel", "fidelity", "revival", "medical", "llc", "inc", "co", "acmee", "dentl"]
    rnd = random.Random(11)
    names = [" ".join(rnd.choice(words) for _ in range(rnd.randint(1, 4))) for _ in range(160)]
    for floor in (0.6, 0.75):
        for a in names:
            for b in names[:50]:
                full, quick = score(a, b), score(a, b, floor)
                assert (quick >= floor) == (full >= floor), (a, b, floor, full, quick)
                if full >= floor:
                    assert quick == full, (a, b, floor)


def test_a_mapping_with_an_unrelated_name_and_no_machine_in_common_is_suspect_worst_first():
    from app.services.client_matching import suspect_mappings

    rows = [
        {"vendor_client_name": "Acme Dental LLC", "client_name": "Acme Dental", "shared_devices": 0},
        {"vendor_client_name": "Harbor Legal", "client_name": "Zephyr Hotels", "shared_devices": 0},
        {"vendor_client_name": "Oak Partners", "client_name": "Birch Holdings", "shared_devices": 7},
        {"vendor_client_name": "Blue Bay Cafe", "client_name": "Granite Works", "shared_devices": 0},
        {"vendor_client_name": "!!!", "client_name": "Anything", "shared_devices": 0},
        {"vendor_client_name": "Sunrise Clinic", "client_name": "Sunrise Clinic Group", "shared_devices": 0},
    ]
    out = suspect_mappings(rows)
    assert {r["vendor_client_name"] for r in out} == {"Harbor Legal", "Blue Bay Cafe"}, "a like name, a shared machine, an empty name and a contained name are left alone"
    assert all(0.0 <= r["score"] < 0.35 for r in out)
    assert out == sorted(out, key=lambda r: (r["score"], r["client_name"].lower()))
    assert suspect_mappings(rows, threshold=0.0) == [], "a threshold of zero flags nothing"

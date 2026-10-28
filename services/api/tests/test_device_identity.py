from app.services.device_identity import hostname_key, normalize_serial


def test_serial_is_trimmed_and_uppercased():
    assert normalize_serial("  5cg1 234abc ") == "5CG1234ABC"


def test_placeholder_and_junk_serials_count_as_none():
    for junk in (
        "To Be Filled By O.E.M.",
        "Default string",
        "0000000",
        "XXXXXXXX",
        "N/A",
        "none",
        "",
        "  ",
        None,
        "123",
        "System Serial Number",
        "123456789",
    ):
        assert normalize_serial(junk) is None, junk


def test_same_machine_serial_matches_across_tools_despite_formatting():
    assert normalize_serial("C02ABC123XYZ") == normalize_serial(" c02abc123xyz\n")


def test_hostname_key_ignores_case_and_domain():
    assert hostname_key("PC-01.corp.local") == hostname_key("pc-01") == "pc-01"
    assert hostname_key(None) == ""


from types import SimpleNamespace as NS  # noqa: E402

from app.services.device_identity import brand_key, ip_brand_pairs, is_placeholder_name, same_brand, usable_ips  # noqa: E402


def dev(i, host, ips=(), brand=None, serial=None):
    return NS(id=i, hostname=host, ip_addresses=list(ips), manufacturer=brand, serial_number=serial)


def test_a_name_that_ends_in_an_address_is_kept_whole_so_two_auvik_names_are_not_one_name():
    assert hostname_key("Device@10.7.220.92") == "device@10.7.220.92"
    assert hostname_key("Device@10.7.220.92") != hostname_key("Device@10.7.20.55")
    assert hostname_key("PC-01.corp.local") == "pc-01"
    assert hostname_key("host.example.com") == "host"


def test_a_made_up_name_is_recognised_and_only_usable_addresses_count():
    assert is_placeholder_name("device@10.7.1.5") and not is_placeholder_name("front-desk")
    assert usable_ips(["10.0.0.1", "0.0.0.0", "127.0.0.1", "169.254.3.4", "fe80::1", "not an ip", " 192.168.1.9 "]) == {
        "10.0.0.1",
        "192.168.1.9",
    }


def test_brands_agree_unless_both_are_stated_and_different():
    assert brand_key("Ubiquiti Inc.") == "ubiquiti"
    assert (
        same_brand("Ubiquiti Inc.", "ubiquiti")
        and same_brand("Ubiquiti Networks", "Ubiquiti")
        and same_brand(None, "Dell")
        and same_brand("", None)
    )
    assert not same_brand("Ubiquiti", "Lantronix")


def test_a_made_up_name_is_paired_with_the_device_that_has_its_address_and_a_compatible_brand_only():
    auvik = dev("a", "Device@10.7.220.92", ["10.7.220.92"], "Ubiquiti")
    unifi = dev("b", "U6-Lite-Lobby", ["10.7.220.92", "10.7.220.1"], "Ubiquiti Inc.")
    other_brand = dev("c", "Serial-Bridge", ["10.7.220.92"], "Lantronix")
    other_ip = dev("d", "U6-Pro", ["10.7.221.5"], "Ubiquiti")
    no_brand = dev("e", "Mystery", ["10.7.220.92"], None)
    tools = {"a": {"auvik"}, "b": {"unifi"}, "c": {"auvik"}, "d": {"unifi"}, "e": {"ninjaone"}}
    assert ip_brand_pairs([auvik, unifi, other_brand, other_ip, no_brand], tools, set(), set()) == [("a", "b"), ("a", "e")]


def test_two_made_up_names_that_share_an_address_are_paired_once_and_dismissed_or_taken_pairs_are_skipped():
    a, b = dev("a", "Device@10.0.0.5", ["10.0.0.5"]), dev("b", "Device@10.0.0.5-2", ["10.0.0.5"])
    assert ip_brand_pairs([a, b], {}, set(), set()) == [("a", "b")]
    assert ip_brand_pairs([a, b], {}, {("a", "b")}, set()) == []
    assert ip_brand_pairs([a, b], {}, set(), {("a", "b")}) == []


def test_two_different_serials_or_two_hardware_units_are_never_paired_by_address():
    a = dev("a", "Device@10.0.0.5", ["10.0.0.5"], serial="AAAA1111")
    assert ip_brand_pairs([a, dev("b", "AP", ["10.0.0.5"], serial="BBBB2222")], {}, set(), set()) == []
    hw_a = dev("x", "Device@10.0.0.9", ["10.0.0.9"])
    hw_b = dev("y", "Switch", ["10.0.0.9"])
    assert ip_brand_pairs([hw_a, hw_b], {"x": {"meraki"}, "y": {"unifi"}}, set(), set()) == []
    assert ip_brand_pairs([hw_a, dev("z", "PC", ["10.0.0.9"])], {"x": {"meraki"}, "z": {"ninjaone"}}, set(), set()) == []


def test_device_that_is_not_made_up_is_not_matched_by_address_at_all():
    assert ip_brand_pairs([dev("a", "PC-A", ["10.0.0.5"]), dev("b", "PC-B", ["10.0.0.5"])], {}, set(), set()) == []


def test_loose_name_key_ignores_punctuation_and_spacing_but_keeps_an_address_name_whole():
    from app.services.device_identity import loose_name_key

    assert loose_name_key("Airport SP - Parking") == loose_name_key("Airport-SP-Parking") == "airportspparking"
    assert loose_name_key("PC-01.corp.local") == "pc01"
    assert loose_name_key("Device@10.7.220.92") == "device@10.7.220.92"
    assert loose_name_key("Device@10.7.220.92") != loose_name_key("Device@10.7.20.55")
    assert loose_name_key("--- ") == ""


def test_mac_key_agrees_across_spellings_and_rejects_anything_that_is_not_a_mac():
    from app.services.device_identity import mac_key

    assert mac_key("1C:6A:1B:49:04:8D") == mac_key("1c-6a-1b-49-04-8d") == mac_key("1C6A1B49048D") == "1c6a1b49048d"
    assert mac_key("SN12345") is None
    assert mac_key("000000000000") is None
    assert mac_key(None) is None


def test_macs_of_reads_a_single_mac_and_a_list_and_ignores_anything_else():
    from app.services.device_merge import macs_of

    assert macs_of({"mac": "1C6A1B49048D", "macs": ["aa:bb:cc:dd:ee:01", "junk", None]}) == {"1c6a1b49048d", "aabbccddee01"}
    assert macs_of({"macs": "not a list"}) == set()
    assert macs_of(None) == set()


# ---- NetBIOS-truncated names -------------------------------------------------------------------------------------------------------------------------------


def _dev(i, hostname, serial=None):
    import uuid
    from types import SimpleNamespace

    return SimpleNamespace(id=uuid.UUID(int=i), hostname=hostname, serial_number=serial, ip_addresses=[], manufacturer=None)


def test_a_name_cut_to_15_characters_is_paired_with_the_full_name_from_other_tools():
    from app.services.device_identity import netbios_truncated_pairs

    cut, full = _dev(1, "NUC-GCR-BBQ1-HO"), _dev(2, "NUC-GCR-BBQ1-HOUSTON", "7V2B8R2")
    tools = {cut.id: {"liongard", "screenconnect"}, full.id: {"ninjaone", "huntress"}}
    assert netbios_truncated_pairs([cut, full], tools, set(), set()) == [(cut.id, full.id)]
    sixteen = _dev(3, "NUC-GCR-SEA2-HOU.local.")  # the first label is 16 characters
    other = _dev(4, "NUC-GCR-SEA2-HOUSTON")
    assert netbios_truncated_pairs([sixteen, other], {sixteen.id: {"auvik"}, other.id: {"ninjaone"}}, set(), set()) == [
        (sixteen.id, other.id)
    ]


def test_only_the_cut_length_pairs_and_only_across_different_tools_and_serials():
    from app.services.device_identity import netbios_truncated_pairs

    short, full = _dev(1, "NUC-GCR-BBQ1"), _dev(2, "NUC-GCR-BBQ1-HOUSTON")  # 12 characters is just a shorter name
    assert netbios_truncated_pairs([short, full], {short.id: {"auvik"}, full.id: {"ninjaone"}}, set(), set()) == []
    a, b = _dev(3, "WS-ACCOUNTING-1"), _dev(4, "WS-ACCOUNTING-10")  # both in the one tool: two machines
    assert netbios_truncated_pairs([a, b], {a.id: {"ninjaone"}, b.id: {"ninjaone", "huntress"}}, set(), set()) == []
    s1, s2 = _dev(5, "NUC-GCR-BBQ1-HO", "AAAAAAA1"), _dev(6, "NUC-GCR-BBQ1-HOUSTON", "BBBBBBB2")
    assert netbios_truncated_pairs([s1, s2], {s1.id: {"auvik"}, s2.id: {"ninjaone"}}, set(), set()) == []
    c, d = _dev(7, "NUC-GCR-BBQ1-HO"), _dev(8, "NUC-GCR-BBQ1-HOUSTON")
    tools = {c.id: {"auvik"}, d.id: {"ninjaone"}}
    assert netbios_truncated_pairs([c, d], tools, {(c.id, d.id)}, set()) == [], "a dismissed pair stays dismissed"
    assert netbios_truncated_pairs([c, d], tools, set(), {(c.id, d.id)}) == [], "a pair already offered is not offered twice"


def test_duplicate_pairs_offers_the_truncated_pair_alongside_the_exact_ones():
    from app.services.device_upsert import duplicate_pairs

    cut, full = _dev(1, "NUC-GCR-BBQ1-HO"), _dev(2, "NUC-GCR-BBQ1-HOUSTON")
    assert duplicate_pairs([cut, full], {cut.id: {"liongard"}, full.id: {"ninjaone"}}, set(), set()) == [(cut.id, full.id)]


def test_macs_of_also_reads_ninjaones_mac_addresses_fact_as_one_string_several_or_a_list():
    from app.services.device_merge import macs_of

    assert macs_of({"facts": {"macAddresses": "C8:53:09:75:E0:4F"}}) == {"c85309 75e04f".replace(" ", "")}
    assert macs_of({"facts": {"macAddresses": "C8:53:09:75:E0:4F, F8:89:D2:9E:DF:43;aa-bb-cc-dd-ee-01"}}) == {
        "c85309 75e04f".replace(" ", ""),
        "f889d29edf43",
        "aabbccddee01",
    }
    assert macs_of({"facts": {"macAddresses": ["C8:53:09:75:E0:4F", "bad"]}}) == {"c8530975e04f"}
    assert macs_of({"facts": "nope"}) == set()
    assert macs_of({"facts": {"macAddresses": 5}}) == set()
    assert macs_of({"macs": ["1c6a1b49048d"], "facts": {"macAddresses": "1C:6A:1B:49:04:8D"}}) == {
        "1c6a1b49048d"
    }, "one MAC from two tools is one MAC"


# ---- what the possible-duplicates list leaves out -------------------------------------------------------------------------------------------------------------


def _row(i, hostname, serial=None, ips=(), maker=None):
    import uuid
    from types import SimpleNamespace

    return SimpleNamespace(id=uuid.UUID(int=i), hostname=hostname, serial_number=serial, ip_addresses=list(ips), manufacturer=maker)


def test_two_auvik_records_under_one_name_are_two_devices_not_duplicates():
    from app.services.device_upsert import duplicate_pairs

    a, b = _row(1, "bridge-2.local."), _row(2, "bridge-2.local.")
    assert duplicate_pairs([a, b], {a.id: {"auvik"}, b.id: {"auvik"}}, set(), set()) == []
    c, d = _row(3, "FRONT-DESK-PC"), _row(4, "FRONT-DESK-PC")
    assert duplicate_pairs([c, d], {c.id: {"ninjaone"}, d.id: {"huntress"}}, set(), set()) == [
        (c.id, d.id)
    ], "different tools under one real name are still offered"
    e, f = _row(5, "FRONT-DESK-PC"), _row(6, "FRONT-DESK-PC")
    assert (
        duplicate_pairs([e, f], {e.id: {"auvik", "ninjaone"}, f.id: {"auvik"}}, set(), set()) == []
    ), "they share an Auvik record, so they are two Auvik devices"
    g, h = _row(7, "FRONT-DESK-PC"), _row(8, "FRONT-DESK-PC")
    assert duplicate_pairs([g, h], {g.id: {"ninjaone"}, h.id: {"ninjaone"}}, set(), set()) == [
        (g.id, h.id)
    ], "a re-installed agent machine is still left for a person"


def test_a_stock_name_or_one_many_devices_carry_is_not_offered():
    from app.services.device_upsert import duplicate_pairs

    ipad1, ipad2 = _row(1, "iPad"), _row(2, "iPad.local.")
    assert duplicate_pairs([ipad1, ipad2], {ipad1.id: {"addigy"}, ipad2.id: {"auvik"}}, set(), set()) == []
    crowd = [_row(i, "KIOSK-LOBBY") for i in range(10, 18)]
    tools = {r.id: {f"tool{i}"} for i, r in enumerate(crowd)}
    assert duplicate_pairs(crowd, tools, set(), set()) == [], "eight devices with one name is a reused name, not one machine"


def test_a_trailing_duplicate_marker_is_not_part_of_the_name():
    from app.services.device_identity import loose_name_key

    # Liongard names a second machine with an already-used name "NAME (1)"; the other tools know it as "NAME".
    assert loose_name_key("NUC-ENCLAVE-AUS (1)") == loose_name_key("NUC-ENCLAVE-AUS") == "nucenclaveaus"
    assert loose_name_key("Server (12)") == "server"
    # Only a marker after a space at the very end: digits that are part of the name, and brackets elsewhere, stay.
    assert loose_name_key("PC-10") == "pc10" and loose_name_key("Lab (A)") == "laba" and loose_name_key("(1)") == "1"
    assert loose_name_key("PC (1) Annex") == "pc1annex"


def test_the_machine_liongard_marks_with_a_number_is_offered_with_the_same_machine_in_the_other_tools():
    from types import SimpleNamespace

    from app.services.device_upsert import duplicate_pairs

    def device(i, hostname):
        return SimpleNamespace(id=i, hostname=hostname, serial_number=None, ip_addresses=[], manufacturer=None)

    liongard, rmm = device("a", "NUC-ENCLAVE-AUS (1)"), device("b", "NUC-ENCLAVE-AUS")
    tools = {"a": {"liongard"}, "b": {"ninjaone", "huntress"}}
    assert duplicate_pairs([liongard, rmm], tools, set(), set()) == [("a", "b")]

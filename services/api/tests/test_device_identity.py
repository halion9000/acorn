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
    assert usable_ips(["10.0.0.1", "0.0.0.0", "127.0.0.1", "169.254.3.4", "fe80::1", "not an ip", " 192.168.1.9 "]) == {"10.0.0.1", "192.168.1.9"}


def test_brands_agree_unless_both_are_stated_and_different():
    assert brand_key("Ubiquiti Inc.") == "ubiquiti"
    assert same_brand("Ubiquiti Inc.", "ubiquiti") and same_brand("Ubiquiti Networks", "Ubiquiti") and same_brand(None, "Dell") and same_brand("", None)
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

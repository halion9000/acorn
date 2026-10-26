from app.services.domain_owner import registrable_domain


def test_registrable_domain_of_hosts_addresses_and_two_part_suffixes():
    assert registrable_domain("webdisk.childrenandfamilies.org") == "childrenandfamilies.org"
    assert registrable_domain("Chris.Ardoin@GoLiveOak.com") == "goliveoak.com"
    assert registrable_domain("www.example.co.uk") == "example.co.uk"
    assert registrable_domain("example.org.") == "example.org"
    assert registrable_domain("a.b.c.example.com") == "example.com"


def test_registrable_domain_is_none_for_anything_that_is_not_a_host():
    for bad in (None, "", "NUC-CFGC-KAUF", "10.1.2.3", "10.1.2.3x", "two words.org", "@", "http://x.org/path"):
        assert registrable_domain(bad) is None, bad

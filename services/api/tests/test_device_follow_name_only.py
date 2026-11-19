"""The name alone identifies a machine only when it is a Windows default name and the record has no serial (roadmap name-only-follow). Pure."""

from app.services import device_follow as f


def test_a_windows_default_name_stands_in_for_a_missing_serial():
    assert f.machine_key("DESKTOP-4F2K9QX", None) == ("", "desktop-4f2k9qx")
    assert f.machine_key("laptop-ab12cd3.corp.local", "") == ("", "laptop-ab12cd3")


def test_a_plain_name_a_placeholder_serial_or_a_real_serial_never_use_the_name_alone():
    assert f.machine_key("FRONTDESK", None) is None, "an ordinary name is not unique"
    assert f.machine_key("DESKTOP-4F2K9QX", "To be filled by O.E.M.") is None, "a placeholder is not a missing serial"
    assert f.machine_key("DESKTOP-4F2K9QX", "5CG1234567") == ("5CG1234567", "desktop-4f2k9qx"), "with a serial, the serial rules as before"
    assert f.machine_key("DESKTOP-4F2K9", None) is None, "seven characters exactly"
    assert f.machine_key("DESKTOP-4F2K9QXZ", None) is None


def test_a_default_name_follows_to_the_one_client_that_holds_it_and_not_when_two_do():
    import uuid

    a, b, heading = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    key = ("", "desktop-4f2k9qx")
    item = (0, "huntress", "DESKTOP-4F2K9QX", None, heading)
    assert f.follow_targets([item], {key: {a}}) == {0: a}
    assert f.follow_targets([item], {key: {a, b}}) == {}
    assert f.follow_targets([(0, "huntress", "FRONTDESK", None, heading)], {key: {a}}) == {}

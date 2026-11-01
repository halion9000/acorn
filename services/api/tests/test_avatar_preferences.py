"""A person's picture is saved with their preferences, so what can be stored there is limited: a small PNG, JPEG or WebP, never a link or an SVG."""

import base64

import pytest
from app.api.v1.endpoints.auth import AVATAR_MAX_CHARS, PreferencesPatch, merge_preferences
from pydantic import ValidationError

# the smallest valid PNG (1 x 1)
PNG = "data:image/png;base64," + base64.b64encode(
    bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000001e221bc330000000049454e44ae426082")
).decode()
JPEG = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xe0" + b"0" * 50).decode()
WEBP = "data:image/webp;base64," + base64.b64encode(b"RIFFxxxxWEBPVP8 " + b"0" * 20).decode()


@pytest.mark.parametrize("picture", [PNG, JPEG, WEBP])
def test_a_small_png_jpeg_or_webp_is_accepted(picture):
    assert PreferencesPatch(preferences={"avatar": picture}).preferences["avatar"] == picture


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param("https://evil.example/pixel.png", id="a link to another site"),
        pytest.param("http://169.254.169.254/latest", id="a link to the cloud metadata address"),
        pytest.param("data:image/svg+xml;base64," + base64.b64encode(b"<svg onload=alert(1)/>").decode(), id="an SVG, which can carry script"),
        pytest.param("data:text/html;base64," + base64.b64encode(b"<script>x</script>").decode(), id="a web page"),
        pytest.param("data:image/png;base64,@@@not base64@@@", id="not base64"),
        pytest.param("javascript:alert(1)", id="a javascript address"),
        pytest.param("data:image/png;base64," + "A" * (AVATAR_MAX_CHARS + 1), id="one character too long"),
        pytest.param(12345, id="a number"),
        pytest.param(["a"], id="a list"),
    ],
)
def test_links_scripts_svgs_oversize_and_junk_are_refused(bad):
    with pytest.raises(ValidationError):
        PreferencesPatch(preferences={"avatar": bad})


def test_empty_or_null_means_remove_and_other_preferences_are_not_checked_for_pictures():
    assert PreferencesPatch(preferences={"avatar": None}).preferences == {"avatar": None}
    assert PreferencesPatch(preferences={"avatar": ""}).preferences == {"avatar": ""}
    assert PreferencesPatch(preferences={"theme": "dark", "profile": {"title": "SOC"}}).preferences["theme"] == "dark"


def test_the_whole_set_of_preferences_has_a_size_limit_too():
    with pytest.raises(ValidationError):
        PreferencesPatch(preferences={"notes": "x" * 300_000})


def test_merging_keeps_other_keys_replaces_the_one_sent_and_removing_a_picture_drops_the_key():
    existing = {"theme": "dark", "avatar": PNG, "profile": {"title": "old"}}
    assert merge_preferences(existing, {"profile": {"title": "new"}}) == {"theme": "dark", "avatar": PNG, "profile": {"title": "new"}}, "saving the profile does not touch the picture"
    assert merge_preferences(existing, {"avatar": JPEG})["avatar"] == JPEG
    assert "avatar" not in merge_preferences(existing, {"avatar": None})
    assert "avatar" not in merge_preferences(existing, {"avatar": ""})
    assert merge_preferences(None, {"theme": "light"}) == {"theme": "light"}

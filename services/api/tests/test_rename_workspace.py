"""A workspace administrator can name the workspace; what can be used as a name is limited."""

import pytest
from app.api.v1.endpoints.tenants import RenameWorkspaceRequest
from pydantic import ValidationError


def test_a_plain_name_is_kept_and_stray_spaces_are_tidied():
    assert RenameWorkspaceRequest(name="  Live   Oak IT ").name == "Live Oak IT"


@pytest.mark.parametrize("bad", ["", " ", "x", "a" * 81, "<script>alert(1)</script>", "Live\x00Oak"])
def test_empty_too_short_too_long_or_markup_is_refused(bad):
    with pytest.raises(ValidationError):
        RenameWorkspaceRequest(name=bad)


def test_the_longest_allowed_name_is_accepted():
    assert len(RenameWorkspaceRequest(name="a" * 80).name) == 80

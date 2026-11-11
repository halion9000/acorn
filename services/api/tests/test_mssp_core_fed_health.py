"""The tools CORE feeds in count for each client they are mapped to (they are saved under your own organization, so a client's own connector count missed them)."""

import uuid

from app.api.v1.endpoints.mssp import with_core_fed

A, B, C = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def test_a_fed_tool_counts_once_for_each_client_it_is_mapped_to_and_is_never_counted_failing():
    health = {A: (2, 1)}
    sources = {A: {"huntress", "ninjaone"}, B: {"ninjaone"}, C: set()}
    fed = {"huntress": False, "ninjaone": True}
    assert with_core_fed(health, sources, fed) == {
        A: (4, 1),
        B: (1, 0),
    }, "a feed's state is shared by every client, so it is not a failure of this client's"


def test_a_tool_that_is_not_fed_by_core_is_not_counted_and_the_input_is_left_alone():
    health = {A: (1, 0)}
    out = with_core_fed(health, {A: {"halopsa", "huntress"}}, {"huntress": False})
    assert out == {A: (2, 0)}
    assert health == {A: (1, 0)}
    assert (
        with_core_fed({}, {A: {"halopsa"}}, {"huntress": False}) == {}
    ), "a client with only unfed tools stays absent: it reads as having none"


def test_nothing_fed_changes_nothing():
    assert with_core_fed({A: (3, 1)}, {A: {"huntress"}}, {}) == {A: (3, 1)}

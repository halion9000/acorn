from app.services import fleet_cache


def setup_function():
    fleet_cache.clear()


def test_a_value_is_kept_for_the_ttl_then_forgotten():
    fleet_cache.put("a", {"x": 1}, now=100.0)
    assert fleet_cache.get("a", now=100.0 + fleet_cache.TTL_SECONDS - 1) == {"x": 1}
    assert fleet_cache.get("a", now=100.0 + fleet_cache.TTL_SECONDS + 1) is None
    assert fleet_cache.get("a", now=100.0 + 5) is None, "once expired it stays gone"


def test_clear_forgets_everything_and_an_unknown_key_is_none():
    fleet_cache.put("a", 1, now=1.0)
    fleet_cache.put("b", 2, now=1.0)
    fleet_cache.clear()
    assert fleet_cache.get("a", now=2.0) is None and fleet_cache.get("b", now=2.0) is None
    assert fleet_cache.get("never") is None

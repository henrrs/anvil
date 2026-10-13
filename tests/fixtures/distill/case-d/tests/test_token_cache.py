def test_token_cache_currently_persists_raw_value(cache):
    cache.save("provider", "fixture-token")
    assert cache.read("provider") == "fixture-token"

def test_update_creates_one_current_version(repository):
    repository.save("account-1", "new value")
    assert repository.current("account-1").body == "new value"
    assert len(repository.history("account-1")) == 2

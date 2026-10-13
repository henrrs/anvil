def test_append_does_not_update_prior_events(store, event):
    before = store.all()
    store.append(event)
    assert store.all()[:-1] == before

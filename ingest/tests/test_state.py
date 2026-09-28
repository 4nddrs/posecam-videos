import json

from ingest.state import JsonStateStore


def test_state_store_round_trips_processed_ids(tmp_path):
    path = tmp_path / "state.json"
    store = JsonStateStore(path)

    assert store.processed_ids() == set()

    store.mark_processed("zip-1")
    store.mark_processed("zip-2")

    assert store.processed_ids() == {"zip-1", "zip-2"}

    reloaded = JsonStateStore(path)
    assert reloaded.processed_ids() == {"zip-1", "zip-2"}

    raw = json.loads(path.read_text())
    assert sorted(raw["processed"]) == ["zip-1", "zip-2"]


def test_state_store_mark_processed_is_idempotent(tmp_path):
    path = tmp_path / "state.json"
    store = JsonStateStore(path)

    store.mark_processed("zip-1")
    store.mark_processed("zip-1")

    assert store.processed_ids() == {"zip-1"}

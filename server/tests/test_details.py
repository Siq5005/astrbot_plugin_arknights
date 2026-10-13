"""The detail store round-trips, tolerates damage and prunes to the window."""

import stat

from app.details import DetailStore


def test_round_trips_through_save_and_load(tmp_path):
    path = tmp_path / "state.json"
    store = DetailStore(path)
    store.put("1", "第一段正文")
    store.put("2", "second body")
    store.save()

    reloaded = DetailStore(path)
    assert reloaded.get("1") == "第一段正文"
    assert reloaded.get("2") == "second body"
    assert reloaded.get("missing") is None


def test_missing_file_starts_empty(tmp_path):
    store = DetailStore(tmp_path / "absent.json")

    assert store.get("1") is None


def test_corrupt_file_starts_empty(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{ not json", encoding="utf-8")

    store = DetailStore(path)

    assert store.get("1") is None


def test_non_object_file_starts_empty(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")

    store = DetailStore(path)

    assert store.get("1") is None


def test_prune_keeps_only_requested_ids(tmp_path):
    path = tmp_path / "state.json"
    store = DetailStore(path)
    store.put("a", "a-body")
    store.put("b", "b-body")
    store.put("c", "c-body")

    store.prune({"b", "c"})

    assert store.get("a") is None
    assert store.get("b") == "b-body"
    assert store.get("c") == "c-body"


def test_save_uses_owner_only_permissions(tmp_path):
    path = tmp_path / "state.json"
    store = DetailStore(path)
    store.put("1", "body")
    store.save()

    assert stat.S_IMODE(path.stat().st_mode) == 0o600

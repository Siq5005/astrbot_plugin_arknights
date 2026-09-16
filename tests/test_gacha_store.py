"""Tests for the on-disk headhunting record store."""

import json

import pytest

from core.gacha_store import GachaStore


def record(category="1", ts="1700000000", pos=0, rarity=2, name="干员"):
    return {
        "category": category,
        "gachaTs": ts,
        "pos": pos,
        "rarity": rarity,
        "charName": name,
    }


@pytest.mark.anyio
async def test_load_returns_empty_for_an_unknown_role(tmp_path):
    store = GachaStore(tmp_path / "gacha.json")
    state = await store.load("1001")
    assert state == {"records": [], "synced_at": 0}


@pytest.mark.anyio
async def test_merge_persists_records(tmp_path):
    path = tmp_path / "gacha.json"
    store = GachaStore(path)
    merged = await store.merge("1001", [record()], synced_at=1234)
    assert merged["synced_at"] == 1234
    assert len(merged["records"]) == 1

    # a fresh instance sees the same data, which is the whole point
    reloaded = await GachaStore(path).load("1001")
    assert reloaded["synced_at"] == 1234
    assert len(reloaded["records"]) == 1


@pytest.mark.anyio
async def test_merge_accumulates_history_instead_of_replacing(tmp_path):
    store = GachaStore(tmp_path / "gacha.json")
    await store.merge("1001", [record(ts="100", pos=1)], synced_at=1)
    # the later sync only returns the newest window
    merged = await store.merge("1001", [record(ts="200", pos=1)], synced_at=2)
    assert [r["gachaTs"] for r in merged["records"]] == ["100", "200"]


@pytest.mark.anyio
async def test_merge_dedupes_on_category_timestamp_and_position(tmp_path):
    store = GachaStore(tmp_path / "gacha.json")
    await store.merge("1001", [record(category="1", ts="100", pos=5)], synced_at=1)
    merged = await store.merge(
        "1001",
        [
            record(category="1", ts="100", pos=5),
            # same cursor but a different category is a different pull
            record(category="2", ts="100", pos=5),
        ],
        synced_at=2,
    )
    assert len(merged["records"]) == 2
    assert {r["category"] for r in merged["records"]} == {"1", "2"}


@pytest.mark.anyio
async def test_merge_sorts_by_time(tmp_path):
    store = GachaStore(tmp_path / "gacha.json")
    merged = await store.merge(
        "1001",
        [record(ts="300"), record(ts="100"), record(ts="200")],
        synced_at=1,
    )
    assert [r["gachaTs"] for r in merged["records"]] == ["100", "200", "300"]


@pytest.mark.anyio
async def test_roles_are_isolated(tmp_path):
    store = GachaStore(tmp_path / "gacha.json")
    await store.merge("1001", [record()], synced_at=1)
    assert await store.load("2002") == {"records": [], "synced_at": 0}


@pytest.mark.anyio
async def test_clear_drops_only_that_role(tmp_path):
    store = GachaStore(tmp_path / "gacha.json")
    await store.merge("1001", [record()], synced_at=1)
    await store.merge("2002", [record()], synced_at=1)
    await store.clear("1001")
    assert (await store.load("1001"))["records"] == []
    assert len((await store.load("2002"))["records"]) == 1


@pytest.mark.anyio
async def test_corrupt_file_is_recovered(tmp_path):
    path = tmp_path / "gacha.json"
    path.write_text("{not json", encoding="utf-8")
    store = GachaStore(path)
    assert await store.load("1001") == {"records": [], "synced_at": 0}
    merged = await store.merge("1001", [record()], synced_at=1)
    assert len(merged["records"]) == 1


@pytest.mark.anyio
async def test_written_file_is_owner_only(tmp_path):
    path = tmp_path / "gacha.json"
    await GachaStore(path).merge("1001", [record()], synced_at=1)
    assert (path.stat().st_mode & 0o777) == 0o600


@pytest.mark.anyio
async def test_merge_ignores_non_dict_entries(tmp_path):
    store = GachaStore(tmp_path / "gacha.json")
    merged = await store.merge("1001", [record(), "junk", None], synced_at=1)
    assert len(merged["records"]) == 1


@pytest.mark.anyio
async def test_store_shape_is_stable(tmp_path):
    path = tmp_path / "gacha.json"
    await GachaStore(path).merge("1001", [record()], synced_at=7)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["roles"]["1001"]["synced_at"] == 7

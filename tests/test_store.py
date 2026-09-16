import json
import os
import stat

import pytest

from core.store import Store


@pytest.mark.anyio
async def test_upsert_and_get_user(tmp_path):
    store = Store(tmp_path / "users.json")
    await store.upsert_auth("u1", "tok", "探姬", [{"uid": "1", "nick_name": "A"}])
    user = await store.get_user("u1")
    assert user["token"] == "tok"
    assert user["skland_nickname"] == "探姬"
    assert user["primary_uid"] == "1"


@pytest.mark.anyio
async def test_get_user_missing_returns_none(tmp_path):
    store = Store(tmp_path / "users.json")
    assert await store.get_user("nobody") is None


@pytest.mark.anyio
async def test_delete_binding_switches_primary(tmp_path):
    store = Store(tmp_path / "users.json")
    await store.upsert_auth(
        "u1",
        "tok",
        "n",
        [{"uid": "1", "nick_name": "A"}, {"uid": "2", "nick_name": "B"}],
    )
    assert await store.delete_binding("u1", "1") is True
    user = await store.get_user("u1")
    assert [b["uid"] for b in user["bindings"]] == ["2"]
    assert user["primary_uid"] == "2"

    assert await store.delete_binding("u1", "2") is True
    assert await store.get_user("u1") is None


@pytest.mark.anyio
async def test_delete_binding_unknown_uid_returns_false(tmp_path):
    store = Store(tmp_path / "users.json")
    await store.upsert_auth("u1", "tok", "n", [{"uid": "1", "nick_name": "A"}])
    assert await store.delete_binding("u1", "999") is False


@pytest.mark.anyio
async def test_set_primary(tmp_path):
    store = Store(tmp_path / "users.json")
    await store.upsert_auth(
        "u1",
        "tok",
        "n",
        [{"uid": "1", "nick_name": "A"}, {"uid": "2", "nick_name": "B"}],
    )
    assert await store.set_primary("u1", "2") is True
    assert (await store.get_user("u1"))["primary_uid"] == "2"
    assert await store.set_primary("u1", "999") is False


@pytest.mark.anyio
async def test_sanity_subscription_toggle(tmp_path):
    store = Store(tmp_path / "users.json")
    await store.set_sanity_sub("u1", "aiocqhttp:FriendMessage:1", True)
    assert await store.list_sanity_subs() == [
        {"user_key": "u1", "umo": "aiocqhttp:FriendMessage:1"}
    ]
    # re-enabling replaces rather than duplicating
    await store.set_sanity_sub("u1", "aiocqhttp:FriendMessage:1", True)
    assert len(await store.list_sanity_subs()) == 1
    await store.set_sanity_sub("u1", "", False)
    assert await store.list_sanity_subs() == []


@pytest.mark.anyio
async def test_sanity_subscription_toggle_keeps_other_users(tmp_path):
    store = Store(tmp_path / "users.json")
    await store.set_sanity_sub("u1", "umo1", True)
    await store.set_sanity_sub("u2", "umo2", True)
    await store.set_sanity_sub("u1", "", False)
    assert await store.list_sanity_subs() == [{"user_key": "u2", "umo": "umo2"}]


@pytest.mark.anyio
async def test_sign_group_toggle(tmp_path):
    store = Store(tmp_path / "users.json")
    await store.set_sign_group("g1", "aiocqhttp:GroupMessage:1", True)
    assert await store.list_sign_groups() == [
        {"group_id": "g1", "umo": "aiocqhttp:GroupMessage:1"}
    ]
    await store.set_sign_group("g1", "", False)
    assert await store.list_sign_groups() == []


@pytest.mark.anyio
async def test_remove_user_is_cleared_from_subscriptions(tmp_path):
    store = Store(tmp_path / "users.json")
    await store.upsert_auth("u1", "tok", "n", [{"uid": "1", "nick_name": "A"}])
    await store.set_sanity_sub("u1", "umo1", True)
    assert await store.remove_user("u1") is True
    assert await store.list_sanity_subs() == []


@pytest.mark.anyio
async def test_upsert_auth_keeps_umo(tmp_path):
    store = Store(tmp_path / "users.json")
    await store.upsert_auth(
        "u1", "tok", "n", [{"uid": "1", "nick_name": "A"}], umo="umo1"
    )
    assert (await store.get_user("u1"))["umo"] == "umo1"
    # re-binding without a umo keeps the previously captured session
    await store.upsert_auth("u1", "tok2", "n", [{"uid": "1", "nick_name": "A"}])
    assert (await store.get_user("u1"))["umo"] == "umo1"


@pytest.mark.anyio
async def test_all_users_returns_bound_accounts(tmp_path):
    store = Store(tmp_path / "users.json")
    await store.upsert_auth("u1", "tok", "n", [{"uid": "1", "nick_name": "A"}])
    await store.upsert_auth("u2", "tok2", "m", [{"uid": "2", "nick_name": "B"}])
    users = await store.all_users()
    assert sorted(users) == ["u1", "u2"]


@pytest.mark.anyio
async def test_file_is_private_and_valid_json(tmp_path):
    path = tmp_path / "users.json"
    store = Store(path)
    await store.upsert_auth("u1", "tok", "n", [{"uid": "1", "nick_name": "A"}])
    assert json.loads(path.read_text(encoding="utf-8"))["users"]["u1"]["token"] == "tok"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


@pytest.mark.anyio
async def test_corrupt_file_is_recovered(tmp_path):
    path = tmp_path / "users.json"
    path.write_text("{not json", encoding="utf-8")
    store = Store(path)
    await store.upsert_auth("u1", "tok", "n", [{"uid": "1", "nick_name": "A"}])
    assert (await store.get_user("u1"))["token"] == "tok"

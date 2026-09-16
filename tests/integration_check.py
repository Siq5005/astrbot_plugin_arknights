"""Integration checks that require the AstrBot framework to be importable.

Run this from the AstrBot root directory (the one containing ``data/plugins``)
using the interpreter AstrBot itself runs with, so the plugin resolves through
the exact dotted module path AstrBot uses at runtime::

    cd /path/to/AstrBot
    ASTRBOT_ROOT=$PWD python /path/to/astrbot_plugin_arknights/tests/integration_check.py

``ASTRBOT_ROOT`` defaults to the current working directory. This exercises the
real command handlers against stubbed network responses, so it covers command
wiring, card building and image rendering together without needing an account.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
ASTRBOT_ROOT = Path(os.environ.get("ASTRBOT_ROOT") or Path.cwd()).resolve()
if not (ASTRBOT_ROOT / "data" / "plugins").is_dir():
    raise SystemExit(
        f"找不到 AstrBot 根目录（{ASTRBOT_ROOT} 下没有 data/plugins）。\n"
        "请在 AstrBot 根目录运行本脚本，或设置 ASTRBOT_ROOT 环境变量。"
    )
sys.path.insert(0, str(PLUGIN_ROOT))
sys.path.insert(0, str(ASTRBOT_ROOT))

import data.plugins.astrbot_plugin_arknights.main as plugin_module  # noqa: E402
from astrbot.core.star.star_handler import star_handlers_registry  # noqa: E402

from core.render import Renderer  # noqa: E402
from core.skland import SignInResult  # noqa: E402
from core.store import Store  # noqa: E402

NOW = time.time()

OPERATORS = [
    ("char_002_amiya", "阿米娅", 4, "CASTER", 90, 2, 5, 200),
    ("char_003_kalts", "凯尔希", 5, "MEDIC", 90, 2, 4, 200),
    ("char_1012_skadi2", "浊心斯卡蒂", 5, "WARRIOR", 90, 2, 3, 145),
    ("char_009_12fce", "12F", 0, "CASTER", 40, 1, 3, 55),
]
CHAR_INFO = {
    cid: {"name": name, "rarity": rarity, "profession": profession}
    for cid, name, rarity, profession, *_ in OPERATORS
}
PLAYER = {
    "status": {
        "name": "探姬#9315",
        "level": 71,
        "registerTs": 1556736265,
        "mainStageProgress": "st_09-01",
        "storeTs": int(NOW) - 900,
        "charCnt": 0,
        "skinCnt": 0,
        "ap": {"current": 88, "max": 135, "completeRecoveryTime": int(NOW) + 4200},
    },
    "chars": [
        {
            "charId": cid,
            "level": level,
            "evolvePhase": elite,
            "potentialRank": potential,
            "favorPercent": favor,
            "defaultSkillId": "skchr_amiya_3",
            "skills": [{"id": "skchr_amiya_3", "specializeLevel": 3}],
            "equip": [{"id": "uniequip_002_amiya", "level": 1}],
        }
        for cid, _n, _r, _p, level, elite, potential, favor in OPERATORS
    ],
    "skins": [{"skinId": "s1"}],
    "charInfoMap": CHAR_INFO,
    "equipmentInfoMap": {"uniequip_002_amiya": {"name": "阿米娅证章"}},
    "assistChars": [
        {"charId": "char_002_amiya", "level": 90, "evolvePhase": 2},
    ],
    "routine": {
        "daily": {"current": 10, "total": 10},
        "weekly": {"current": 9, "total": 13},
    },
    "campaign": {"reward": {"current": 1200, "total": 1725}},
}

EXPECTED_COMMANDS = {
    "方舟帮助",
    "方舟绑定",
    "方舟绑定列表",
    "方舟切换绑定",
    "方舟删除绑定",
    "方舟便签",
    "方舟理智",
    "方舟签到",
    "方舟订阅理智",
    "方舟取消订阅理智",
    "方舟订阅签到",
    "方舟取消订阅签到",
    "方舟干员列表",
    "方舟干员",
    "方舟面板",
}

# Commands registered by astrbot_plugin_endfield that must never be claimed by
# this plugin, otherwise a single message would be handled by both plugins.
ENDFIELD_COMMANDS = {
    "zmd",
    "便签",
    "全服统计",
    "公告",
    "公告最新",
    "切换绑定",
    "删除绑定",
    "危机合约",
    "取消订阅公告",
    "取消订阅理智",
    "取消订阅调度券",
    "同步面板",
    "国际服登录",
    "地区建设",
    "帝江号建设",
    "干员列表",
    "成就列表",
    "手机绑定",
    "扫码绑定",
    "抽卡分析",
    "抽卡分析同步",
    "抽卡记录",
    "授权登陆",
    "日历",
    "理智",
    "签到",
    "绑定列表",
    "订阅公告",
    "订阅理智",
    "订阅调度券",
}

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}{f' — {detail}' if detail else ''}")
    if not condition:
        failures.append(name)


class StubEvent:
    """Duck-typed stand-in for AstrMessageEvent covering the handlers' surface."""

    def __init__(self, text: str, sender: str = "10001", private: bool = True) -> None:
        self.message_str = text
        self.unified_msg_origin = f"test:PrivateMessage:{sender}"
        self._sender = sender
        self._private = private

    def get_sender_id(self) -> str:
        return self._sender

    def is_private_chat(self) -> bool:
        return self._private

    def get_group_id(self) -> str:
        return "" if self._private else "20002"

    def get_platform_name(self) -> str:
        return "test"

    def plain_result(self, text: str):
        return ("plain", text)

    def chain_result(self, chain):
        return ("chain", chain)


def registered_commands() -> set[str]:
    """Collect command names this plugin registered with AstrBot."""
    names: set[str] = set()
    for handler in star_handlers_registry._handlers:
        if "astrbot_plugin_arknights" not in (handler.handler_module_path or ""):
            continue
        for event_filter in handler.event_filters:
            command_name = getattr(event_filter, "command_name", None)
            if command_name:
                names.add(command_name)
                names.update(getattr(event_filter, "alias", set()) or set())
    return names


def astrbot_detected_conflicts() -> dict[str, list[str]]:
    """Ask AstrBot's own command manager which command names are claimed twice.

    AstrBot ships a command management module that powers the dashboard's
    conflict view. Its grouping helper needs no database, so it is reused here to
    check this plugin against every other plugin loaded into the process.

    Returns:
        Mapping of duplicated command name to the plugins claiming it.
    """
    from astrbot.core.star.command_management import (  # noqa: PLC0415
        _collect_descriptors,
        _group_conflicts,
    )

    descriptors = _collect_descriptors(include_sub_commands=False)
    return {
        name: [desc.plugin_name for desc in group]
        for name, group in _group_conflicts(descriptors).items()
    }


async def drive(agen) -> list:
    """Collect the yielded results of a command handler."""
    return [item async for item in agen]


async def main() -> int:
    check(
        "plugin imports via data.plugins.<name>.main",
        plugin_module.ArknightsPlugin.__name__ == "ArknightsPlugin",
    )
    check(
        "metadata name matches plugin directory",
        plugin_module.PLUGIN_NAME == "astrbot_plugin_arknights",
    )

    registered = registered_commands()
    missing = EXPECTED_COMMANDS - registered
    check(
        "all expected commands registered",
        not missing,
        f"missing: {sorted(missing)}"
        if missing
        else f"{len(EXPECTED_COMMANDS)}/{len(EXPECTED_COMMANDS)}",
    )

    # The whole point of the 方舟 prefix: a message must never be claimed by both
    # this plugin and astrbot_plugin_endfield.
    overlap = registered & ENDFIELD_COMMANDS
    check(
        "no command name collides with astrbot_plugin_endfield",
        not overlap,
        f"colliding: {sorted(overlap)}" if overlap else "0 collisions",
    )

    # Cross-check with AstrBot's own conflict detector, with the Endfield plugin
    # loaded into the same process so the registry holds both plugins.
    endfield_loaded = False
    try:
        import data.plugins.astrbot_plugin_endfield.main  # noqa: F401, PLC0415

        endfield_loaded = True
    except Exception as exc:  # noqa: BLE001 - the check degrades to a notice
        print(f"[SKIP] astrbot_plugin_endfield 未加载，跳过交叉冲突检测: {exc}")

    if endfield_loaded:
        conflicts = astrbot_detected_conflicts()
        mine = {
            name: plugins
            for name, plugins in conflicts.items()
            if any("arknights" in (plugin or "") for plugin in plugins)
        }
        check(
            "AstrBot 自带冲突检测未报告本插件冲突",
            not mine,
            f"冲突: {mine}" if mine else "0 conflicts",
        )
        others = {
            name: plugins for name, plugins in conflicts.items() if name not in mine
        }
        print(
            f"       （其他插件之间存在 {len(others)} 组冲突，与本插件无关"
            + (f"：{sorted(others)}" if others else "")
            + "）"
        )

    plugin = plugin_module.ArknightsPlugin(
        context=SimpleNamespace(send_message=None), config={}
    )
    plugin.store = Store(Path("/tmp/ak-integration/users.json"))
    plugin.store.path.unlink(missing_ok=True)
    renderer = Renderer(
        PLUGIN_ROOT / "templates", Path("/tmp/ak-integration/cache"), 30000
    )
    plugin._renderer = renderer

    async def fake_authorization(token: str) -> str:
        return "auth-code"

    async def fake_credential(authorization: str):
        return SimpleNamespace(token="t", cred="c")

    async def fake_player_info(cred, uid: str) -> dict:
        return PLAYER

    async def fake_sign(cred, binding) -> SignInResult:
        return SignInResult(
            success=True, nickname=binding.nickname, awards=["合成玉x500"]
        )

    plugin.skland.get_authorization = fake_authorization
    plugin.skland.get_credential = fake_credential
    plugin.skland.get_player_info = fake_player_info
    plugin.skland.sign_arknights = fake_sign

    # Unbound user
    await plugin.store.remove_user("10001")
    results = await drive(plugin.show_note(StubEvent("/方舟便签")))
    check(
        "方舟便签 without binding prompts to bind",
        results and results[0][0] == "plain" and "方舟绑定" in results[0][1],
        results[0][1] if results else "no result",
    )

    # Bind, then exercise every card command
    await plugin.store.upsert_auth(
        "10001",
        "token",
        "探姬",
        [
            {
                "uid": "1",
                "game_id": "1",
                "nick_name": "探姬#9315",
                "channel_name": "官服",
            }
        ],
        umo="test:PrivateMessage:10001",
    )

    for command, handler, label in (
        ("/方舟便签", "show_note", "方舟便签"),
        ("/方舟理智", "show_sanity", "方舟理智"),
        ("/方舟干员列表", "show_roster", "方舟干员列表"),
    ):
        results = await drive(getattr(plugin, handler)(StubEvent(command)))
        image_ok = (
            results
            and results[0][0] == "chain"
            and getattr(results[0][1][0], "path", None)
            and Path(results[0][1][0].path).is_file()
        )
        check(f"{label} renders an image", bool(image_ok))

    # Operator detail by argument; the form deliberately does not end in 面板 so
    # that the Endfield plugin's "xx面板" regex cannot also match it.
    results = await drive(plugin.show_operator(StubEvent("/方舟干员 阿米娅")))
    check(
        "方舟干员 <名称> renders the detail card",
        results and results[0][0] == "chain" and Path(results[0][1][0].path).is_file(),
    )

    results = await drive(plugin.show_operator(StubEvent("/方舟面板 阿米娅")))
    check(
        "方舟面板 alias works too",
        results and results[0][0] == "chain" and Path(results[0][1][0].path).is_file(),
    )

    results = await drive(plugin.show_operator(StubEvent("/方舟干员 不存在")))
    check(
        "unknown operator reports a friendly hint",
        results and results[0][0] == "plain" and "未找到干员" in results[0][1],
    )

    results = await drive(plugin.show_operator(StubEvent("/方舟干员")))
    check(
        "方舟干员 without a name prints usage",
        results and results[0][0] == "plain" and "用法" in results[0][1],
    )

    results = await drive(plugin.do_sign(StubEvent("/方舟签到")))
    check("方舟签到 reports the awards", results and "合成玉x500" in results[0][1])

    results = await drive(plugin.list_bindings(StubEvent("/方舟绑定列表")))
    check(
        "方舟绑定列表 shows the role but never the token",
        results and "token" not in results[0][1] and "1. 探姬#9315" in results[0][1],
        results[0][1].replace("\n", " | ") if results else "no result",
    )

    results = await drive(plugin.show_help(StubEvent("/方舟帮助")))
    check("方舟帮助 renders the help card", results and results[0][0] == "chain")

    # Scheduler configuration
    plugin.config = {"sign_time": "03:30", "sanity_poll_interval": 5}
    check(
        "sign time parses",
        plugin._parse_sign_time(plugin.config["sign_time"]) == (3, 30),
    )
    await plugin.initialize()
    check("scheduler starts with two jobs", plugin.scheduler is not None)
    await plugin.terminate()
    check("terminate shuts the scheduler down", plugin.scheduler is None)

    await renderer.close()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {failures}")
        return 1
    print("all integration checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

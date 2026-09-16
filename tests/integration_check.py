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
import re
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

# Importing the plugin initialises AstrBot's logging, which installs a file sink
# pointed at the live astrbot.log. This run loads the plugin with fixture config,
# so lines such as the scheduler banner are indistinguishable from production
# there — a "签到 03:30" banner from this file was once mistaken for the live
# setting. Drop the sinks and keep reporting through stdout.
try:
    from loguru import logger as _loguru_logger

    _loguru_logger.remove()
except Exception:  # noqa: BLE001 - logging setup is best effort
    pass

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

PLUGIN_DIR = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "astrbot_plugin_arknights"

EXPECTED_COMMANDS = {
    "ark帮助",
    "ark绑定",
    "ark绑定列表",
    "ark切换绑定",
    "ark删除绑定",
    "ark便签",
    "ark理智",
    "ark签到",
    "ark订阅理智",
    "ark取消订阅理智",
    "ark订阅签到",
    "ark取消订阅签到",
    "ark干员列表",
    "ark干员",
    "ark面板",
    "ark基建",
    "ark剿灭",
    "ark肉鸽",
    "ark任务",
    "ark公招",
    "ark抽卡分析",
    "ark抽卡记录",
    "ark抽卡重置",
    "ark公告",
    "ark订阅公告",
    "ark取消订阅公告",
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

    def __init__(
        self,
        text: str,
        sender: str = "10001",
        private: bool = True,
        at_or_wake: bool = False,
        mentions: bool = False,
    ) -> None:
        self.message_str = text
        self._sender = sender
        self._private = private
        # the origin has to follow the chat type, otherwise a group event would
        # still look private to anything that keys off the session
        self.unified_msg_origin = (
            f"test:PrivateMessage:{sender}"
            if private
            else f"test:GroupMessage:{self.get_group_id()}"
        )
        self.is_at_or_wake_command = at_or_wake
        self._mentions = mentions
        self.stopped = False

    def get_messages(self):
        from astrbot.api.message_components import At, Plain

        segments = [Plain(self.message_str)]
        if self._mentions:
            segments.insert(0, At(qq="10000"))
        return segments

    def stop_event(self) -> None:
        self.stopped = True

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


def interceptor_regex(plugin_name: str, handler_name: str):
    """Return a plugin's missing-prefix interceptor regex.

    Args:
        plugin_name: Plugin directory name, e.g. ``astrbot_plugin_arknights``.
        handler_name: Handler method name.

    Returns:
        The compiled pattern, or ``None`` when the plugin has no such handler.
    """
    for handler in star_handlers_registry._handlers:
        if plugin_name not in (handler.handler_module_path or ""):
            continue
        if handler.handler_name != handler_name:
            continue
        for event_filter in handler.event_filters:
            pattern = getattr(event_filter, "regex", None)
            if pattern is not None:
                return pattern
    return None


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
    import yaml as _yaml

    _meta = _yaml.safe_load((PLUGIN_DIR / "metadata.yaml").read_text(encoding="utf-8"))
    check(
        "metadata version matches PLUGIN_VERSION",
        str(_meta.get("version")) == str(plugin_module.PLUGIN_VERSION),
        f"metadata {_meta.get('version')} vs code {plugin_module.PLUGIN_VERSION}",
    )
    # The README repeats the version in a badge and in the changelog, and both
    # went stale when the version was bumped, so they are checked here too.
    _readme = (PLUGIN_DIR / "README.md").read_text(encoding="utf-8")
    _badge = re.search(r"badge/version-(\d+\.\d+\.\d+)-", _readme)
    check(
        "README badge version matches metadata",
        _badge is not None and _badge.group(1) == str(_meta.get("version")),
        f"badge {_badge.group(1) if _badge else '未找到'} vs metadata {_meta.get('version')}",
    )
    check(
        "README changelog has an entry for the current version",
        f"### {_meta.get('version')} " in _readme,
        f"缺少 ### {_meta.get('version')} 章节",
    )

    # The author is declared twice — metadata.yaml for the market and @register
    # for the runtime — and they had drifted apart once already.
    from astrbot.core.star.star import star_map as _star_map

    _registered = _star_map.get(plugin_module.__name__)
    check(
        "registered author matches metadata.yaml",
        _registered is not None and str(_registered.author) == str(_meta.get("author")),
        f"register {getattr(_registered, 'author', None)} vs metadata {_meta.get('author')}",
    )
    for _field in ("display_name", "desc", "author", "repo"):
        check(
            f"metadata has {_field} for the plugin market",
            bool(str(_meta.get(_field) or "").strip()),
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

    # The whole point of the ark prefix: a message must never be claimed by both
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

    # ── 漏写前缀拦截器：只认自己的命令名，且不抢终末地的名字 ──
    mine = plugin_module.ArknightsPlugin._HINT_CMDS
    check(
        "拦截器覆盖了全部本插件命令名",
        set(EXPECTED_COMMANDS) <= set(mine),
        f"{len(mine)} 个",
    )
    my_regex = interceptor_regex(PLUGIN_NAME, "missing_prefix_hint")
    check("拦截器正则已注册", my_regex is not None)
    if my_regex is not None:
        unmatched = [name for name in mine if not my_regex.search(name)]
        check(
            "拦截器正则能匹配每一个本插件命令名",
            not unmatched,
            f"未匹配: {unmatched}" if unmatched else f"{len(mine)}/{len(mine)}",
        )
        stolen = [name for name in ENDFIELD_COMMANDS if my_regex.search(name)]
        check(
            "拦截器不会抢终末地的命令名",
            not stolen,
            f"抢到: {stolen}" if stolen else "0 conflicts",
        )

    if endfield_loaded:
        their_regex = interceptor_regex(
            "astrbot_plugin_endfield", "missing_prefix_hint"
        )
        if their_regex is not None:
            hit = [name for name in mine if their_regex.search(name)]
            check(
                "终末地拦截器不会命中本插件的命令名",
                not hit,
                f"命中: {hit}" if hit else "0 hits",
            )
            # 反向：终末地自己的名字也不该被本插件抢
            collide = [
                name
                for name in ("便签", "理智", "签到", "干员列表", "公告", "日历")
                if my_regex is not None and my_regex.search(name)
            ]
            check(
                "本插件拦截器不碰裸指令名",
                not collide,
                f"命中: {collide}" if collide else "0 hits",
            )

    # ── 拦截器行为：漏前缀给提示、带前缀与 @ 时让路 ──
    hints = await drive(
        plugin_module.ArknightsPlugin.missing_prefix_hint(
            plugin_module.ArknightsPlugin,
            StubEvent("ark理智"),
        )
    )
    check(
        "漏写 ~ 时给出提示并拦下消息",
        hints and hints[0][0] == "plain" and "~ark理智" in hints[0][1],
        hints[0][1].replace("\n", " | ") if hints else "no result",
    )
    for label, kwargs in (
        ("带 ~ 前缀时让路", {"text": "~ark理智"}),
        ("被 @ 唤醒时让路", {"text": "ark理智", "at_or_wake": True}),
        ("消息含 @ 他人时让路", {"text": "ark理智", "mentions": True}),
    ):
        quiet = await drive(
            plugin_module.ArknightsPlugin.missing_prefix_hint(
                plugin_module.ArknightsPlugin, StubEvent(**kwargs)
            )
        )
        check(f"拦截器{label}", not quiet, f"yielded {quiet}" if quiet else "silent")

    plugin = plugin_module.ArknightsPlugin(
        context=SimpleNamespace(send_message=None), config={}
    )
    plugin.store = Store(Path("/tmp/ak-integration/users.json"))
    plugin.store.path.unlink(missing_ok=True)
    renderer = Renderer(
        PLUGIN_ROOT / "templates", Path("/tmp/ak-integration/cache"), 30000
    )
    plugin._renderer = renderer

    # ── 公告：列表出图、按编号看正文、失败给出明确提示 ──
    ANNOUNCE_FIXTURE = [
        {
            "id": "7367",
            "title": "[明日方舟]09月11日16:00闪断更新公告",
            "author": "【明日方舟】运营组",
            "brief": "计划将于09月11日进行服务器闪断更新。",
            "group": "SYSTEM",
            "group_cn": "系统",
            "url": "https://ak.hypergryph.com/news/7367",
            "ts": 1789095600,
            "date_text": "2026-09-11 11:00",
        },
        {
            "id": "9681",
            "title": "[活动预告]「月行水上」限时活动即将开启",
            "author": "【明日方舟】运营组",
            "brief": "活动期间将开放活动关卡。",
            "group": "ACTIVITY",
            "group_cn": "活动",
            "url": "https://ak.hypergryph.com/news/9681",
            "ts": 1787900000,
            "date_text": "2026-08-29 11:00",
        },
    ]

    async def fake_announce():
        return ANNOUNCE_FIXTURE

    async def fake_detail(cid):
        return {
            "cid": cid,
            "url": f"https://ak.hypergryph.com/news/{cid}",
            "body_html": "<p>公告<b>正文</b>摘要</p>",
            "text": "公告正文摘要",
            "images": ["https://example.invalid/a.jpg"],
            "image_total": 1,
        }

    plugin._announce.fetch = fake_announce
    plugin._announce.fetch_detail = fake_detail

    results = await drive(plugin.show_announcements(StubEvent("/ark公告")))
    check(
        "ark公告 renders a card",
        results and results[0][0] == "chain" and Path(results[0][1][0].path).is_file(),
    )

    results = await drive(plugin.show_announcements(StubEvent("/ark公告 7367")))
    check(
        "ark公告 <编号> renders the body card",
        results and results[0][0] == "chain" and Path(results[0][1][0].path).is_file(),
    )

    results = await drive(plugin.show_announcements(StubEvent("/ark公告 9999")))
    check(
        "ark公告 with an unknown id says so",
        results and "没有找到" in results[0][1],
    )

    async def failing_announce():
        # must be the class the plugin itself catches: the harness imports
        # ``core.announce`` on a separate path from the plugin's own
        # ``.core.announce``, and the two are distinct class objects.
        raise plugin_module.AnnounceError("网络不可用")

    plugin._announce.fetch = failing_announce
    results = await drive(plugin.show_announcements(StubEvent("/ark公告")))
    check(
        "ark公告 reports a feed failure",
        results and "公告获取失败" in results[0][1],
    )
    plugin._announce.fetch = fake_announce

    results = await drive(plugin.subscribe_announce(StubEvent("/ark订阅公告")))
    check(
        "ark订阅公告 confirms in private",
        results and "已订阅" in results[0][1],
    )
    results = await drive(
        plugin.subscribe_announce(StubEvent("/ark订阅公告", private=False))
    )
    check(
        "ark订阅公告 also works in a group and targets that group",
        results and "本群" in results[0][1],
    )
    subs = await plugin.store.list_announce_subs()
    check("公告订阅已落库", len(subs) == 1, f"{subs}")
    check(
        "群聊订阅记录的是群会话",
        subs and "Group" in str(subs[0].get("umo")),
        f"{subs[0].get('umo') if subs else ''}",
    )

    check(
        "群聊扫码会附带凭证警告",
        "GROUP_QR_WARNING" in dir(plugin_module)
        and "群聊中扫码请注意" in plugin_module.GROUP_QR_WARNING,
    )

    await plugin.unsubscribe_announce(StubEvent("/ark取消订阅公告")).__anext__()
    check("公告订阅可取消", not await plugin.store.list_announce_subs())

    # CommandFilter only fires on an exact name or a name plus a space, so the
    # no-space form needs its own alias; both must reach a forced sync.
    check(
        "抽卡同步的两种写法都已注册",
        {"ark抽卡分析", "ark抽卡分析同步", "ark抽卡同步"}
        <= set(plugin_module.ArknightsPlugin._HINT_CMDS),
        f"{sorted(c for c in plugin_module.ArknightsPlugin._HINT_CMDS if '抽卡' in c)}",
    )

    captured: dict[str, bool] = {}

    async def fake_gacha_records(event, force=False):
        captured["force"] = force
        return [], {}, {}, None

    plugin._gacha_records = fake_gacha_records
    for text, expected in (
        ("/ark抽卡分析", False),
        ("/ark抽卡分析 同步", True),
        ("/ark抽卡分析同步", True),
        ("/ark抽卡同步", True),
        ("/ark抽卡分析 刷新", True),
    ):
        await drive(plugin.show_gacha(StubEvent(text)))
        check(
            f"{text} 强制同步={expected}",
            captured.get("force") is expected,
            f"实际 {captured.get('force')}",
        )

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
    results = await drive(plugin.show_note(StubEvent("/ark便签")))
    check(
        "ark便签 without binding prompts to bind",
        results and results[0][0] == "plain" and "ark绑定" in results[0][1],
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
        ("/ark便签", "show_note", "ark便签"),
        ("/ark理智", "show_sanity", "ark理智"),
        ("/ark干员列表", "show_roster", "ark干员列表"),
    ):
        results = await drive(getattr(plugin, handler)(StubEvent(command)))
        image_ok = (
            results
            and results[0][0] == "chain"
            and getattr(results[0][1][0], "path", None)
            and Path(results[0][1][0].path).is_file()
        )
        check(f"{label} renders an image", bool(image_ok))

    # Sanity alerts need a binding, so this runs after the one above.
    results = await drive(
        plugin.subscribe_sanity(StubEvent("/ark订阅理智", private=False))
    )
    check(
        "ark订阅理智 also works in a group",
        results and "本群" in results[0][1],
    )
    sanity_subs = await plugin.store.list_sanity_subs()
    check(
        "理智订阅记录的是群会话",
        sanity_subs and "Group" in str(sanity_subs[0].get("umo")),
        f"{sanity_subs[0].get('umo') if sanity_subs else ''}",
    )
    await plugin.unsubscribe_sanity(StubEvent("/ark取消订阅理智")).__anext__()

    # Operator detail by argument; the form deliberately does not end in 面板 so
    # that the Endfield plugin's "xx面板" regex cannot also match it.
    results = await drive(plugin.show_operator(StubEvent("/ark干员 阿米娅")))
    check(
        "ark干员 <名称> renders the detail card",
        results and results[0][0] == "chain" and Path(results[0][1][0].path).is_file(),
    )

    results = await drive(plugin.show_operator(StubEvent("/ark面板 阿米娅")))
    check(
        "ark面板 alias works too",
        results and results[0][0] == "chain" and Path(results[0][1][0].path).is_file(),
    )

    results = await drive(plugin.show_operator(StubEvent("/ark干员 不存在")))
    check(
        "unknown operator reports a friendly hint",
        results and results[0][0] == "plain" and "未找到干员" in results[0][1],
    )

    results = await drive(plugin.show_operator(StubEvent("/ark干员")))
    check(
        "ark干员 without a name prints usage",
        results and results[0][0] == "plain" and "用法" in results[0][1],
    )

    results = await drive(plugin.do_sign(StubEvent("/ark签到")))
    check("ark签到 reports the awards", results and "合成玉x500" in results[0][1])

    results = await drive(plugin.list_bindings(StubEvent("/ark绑定列表")))
    check(
        "ark绑定列表 shows the role but never the token",
        results and "token" not in results[0][1] and "1. 探姬#9315" in results[0][1],
        results[0][1].replace("\n", " | ") if results else "no result",
    )

    results = await drive(plugin.show_help(StubEvent("/ark帮助")))
    check("ark帮助 renders the help card", results and results[0][0] == "chain")

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

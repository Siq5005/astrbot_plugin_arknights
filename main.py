"""AstrBot entry point for the Arknights (罗德岛终端) plugin.

This is the only module that touches the AstrBot framework; every protocol
detail lives under ``core/`` so it can be unit tested without the framework.
"""

from __future__ import annotations

import asyncio
import base64
import io
import random
import time
from pathlib import Path
from typing import Any

import qrcode
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Image, Plain
from astrbot.api.star import Context, Star, register
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from .core.cards import build_note_context, build_sanity_context
from .core.hypergryph import HypergryphClient, HypergryphError
from .core.operators import (
    build_operator_context,
    build_roster_context,
    find_operator,
    group_operators,
)
from .core.render import Renderer
from .core.skland import SignInResult, SklandClient, SklandError, UserBinding
from .core.store import Store

PLUGIN_NAME = "astrbot_plugin_arknights"
PLUGIN_VERSION = "0.1.0"

# Seconds the QR code stays valid, and how often it is polled.
QR_TIMEOUT = 120
QR_POLL_INTERVAL = 2

QR_PROMPT = """请使用「森空岛」APP 扫描二维码完成登录

1. 打开森空岛 APP
2. 点击右上角「+」→「扫一扫」
3. 扫描下方二维码并确认登录

二维码 2 分钟内有效；登录成功、超时或被拒后会自动撤回。"""

NO_BINDING_TEXT = "你还没有绑定账号。请在私聊发送 `方舟绑定` 扫码登录。"

# Substrings that indicate the stored passport token is no longer usable.
AUTH_ERROR_MARKERS = ("未登录", "失效", "过期", "unauthorized", "401", "403")

# Every command is namespaced with 方舟 so that it can never collide with the
# Endfield plugin (which registers bare 理智 / 便签 / 签到 / 扫码绑定 ... and a
# permissive "xx面板" regex). Keep this prefix on every command.
CMD_PREFIX = "方舟"

HELP_TEXT = """罗德岛终端 · 明日方舟助手

所有指令以 `方舟` 开头，避免与终末地插件（zmd）的同名指令冲突。

【账号绑定】（请私聊使用）
方舟绑定              使用森空岛 APP 扫码登录（唯一登录方式）
方舟绑定列表          查看所有绑定账号
方舟切换绑定 <序号>    切换主账号
方舟删除绑定 <序号>    解绑指定账号

【数据查询】
方舟便签              账号总览
方舟理智              理智与回满时间
方舟干员列表          已持有干员图鉴
方舟干员 <干员名>      单个干员详情

【签到与提醒】
方舟签到              手动执行森空岛签到
方舟订阅理智 / 方舟取消订阅理智  理智回满推送
方舟订阅签到 / 方舟取消订阅签到  群内签到结果通知

账号凭证仅保存在本机，且不会在任何回复中回显。
"""

# Structured copy of HELP_TEXT used by the rendered help card.
HELP_SECTIONS = [
    {
        "title": "账号绑定（请私聊使用）",
        "items": [
            {"cmd": "方舟绑定", "desc": "森空岛 APP 扫码登录（唯一登录方式）"},
            {"cmd": "方舟绑定列表", "desc": "查看所有绑定账号"},
            {"cmd": "方舟切换绑定 <序号>", "desc": "切换主账号"},
            {"cmd": "方舟删除绑定 <序号>", "desc": "解绑指定账号"},
        ],
    },
    {
        "title": "数据查询",
        "items": [
            {"cmd": "方舟便签", "desc": "账号总览"},
            {"cmd": "方舟理智", "desc": "理智与回满时间"},
            {"cmd": "方舟干员列表", "desc": "已持有干员图鉴"},
            {"cmd": "方舟干员 <干员名>", "desc": "单个干员详情"},
        ],
    },
    {
        "title": "签到与提醒",
        "items": [
            {"cmd": "方舟签到", "desc": "手动执行森空岛签到"},
            {"cmd": "方舟订阅理智 / 方舟取消订阅理智", "desc": "理智回满推送"},
            {"cmd": "方舟订阅签到 / 方舟取消订阅签到", "desc": "群内签到结果通知"},
        ],
    },
]


@register(PLUGIN_NAME, "coe", "罗德岛终端", PLUGIN_VERSION)
class ArknightsPlugin(Star):
    """Arknights data query and sign-in plugin."""

    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        """Initialize the plugin.

        Args:
            context: AstrBot plugin context.
            config: Plugin configuration parsed from ``_conf_schema.json``.
        """
        super().__init__(context)
        self.config: dict[str, Any] = config if config is not None else {}
        self.store = Store()
        self.skland = SklandClient()
        self.hypergryph = HypergryphClient()
        self._qr_tasks: set[asyncio.Task[None]] = set()
        self._templates_dir = Path(__file__).parent / "templates"
        self._renderer: Renderer | None = None
        self._base_css: str | None = None
        # uid -> (expiry timestamp, player info payload)
        self._player_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        # user_key -> whether a sanity-full notice has already been sent
        self._sanity_notified: dict[str, bool] = {}
        self.scheduler: AsyncIOScheduler | None = None

    async def initialize(self) -> None:
        """Start the automatic sign-in and sanity polling jobs."""
        hour, minute = self._parse_sign_time(self.config.get("sign_time", "00:05"))
        minutes = max(10, int(self.config.get("sanity_poll_interval", 20) or 20))
        try:
            self.scheduler = AsyncIOScheduler()
            self.scheduler.add_job(
                self._auto_sign_job,
                CronTrigger(hour=hour, minute=minute),
                id="arknights_auto_sign",
                replace_existing=True,
            )
            self.scheduler.add_job(
                self._sanity_poll_job,
                IntervalTrigger(minutes=minutes),
                id="arknights_sanity_poll",
                replace_existing=True,
            )
            self.scheduler.start()
            logger.info(
                "罗德岛终端定时任务已启动：签到 %02d:%02d，理智轮询每 %d 分钟",
                hour,
                minute,
                minutes,
            )
        except Exception as exc:  # noqa: BLE001 - scheduling must not block loading
            logger.error("启动定时任务失败: %s", exc)
            self.scheduler = None

    @staticmethod
    def _parse_sign_time(raw: Any) -> tuple[int, int]:
        """Parse the configured ``HH:MM`` sign-in time.

        Args:
            raw: Configured value.

        Returns:
            Tuple of ``(hour, minute)``, falling back to ``(0, 5)`` when invalid.
        """
        try:
            hour_text, _, minute_text = str(raw or "").partition(":")
            hour, minute = int(hour_text), int(minute_text)
        except (TypeError, ValueError):
            return 0, 5
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
        return 0, 5

    async def terminate(self) -> None:
        """Release network resources and cancel background tasks."""
        if self.scheduler is not None:
            try:
                self.scheduler.shutdown(wait=False)
            except Exception as exc:  # noqa: BLE001 - shutdown must not raise
                logger.debug("关闭定时任务失败: %s", exc)
            self.scheduler = None
        for task in list(self._qr_tasks):
            task.cancel()
        self._qr_tasks.clear()
        if self._renderer is not None:
            await self._renderer.close()
            self._renderer = None
        await self.skland.close()
        await self.hypergryph.close()

    # ── helpers ───────────────────────────────────────────────────────────

    async def _render(self, template: str, data: dict[str, Any]) -> Path | None:
        """Render a card image.

        Args:
            template: Template filename inside the plugin's ``templates`` dir.
            data: Template variables.

        Returns:
            Path of the rendered image, or ``None`` when rendering is unavailable
            so the caller can fall back to text.
        """
        if self._renderer is None:
            cache_dir = (
                Path(get_astrbot_plugin_data_path()) / PLUGIN_NAME / "render_cache"
            )
            self._renderer = Renderer(
                self._templates_dir,
                cache_dir,
                int(self.config.get("render_timeout", 30000) or 30000),
            )
        if self._base_css is None:
            try:
                self._base_css = (self._templates_dir / "base.css").read_text(
                    encoding="utf-8"
                )
            except OSError as exc:
                logger.error("读取 base.css 失败: %s", exc)
                self._base_css = ""
        payload: dict[str, Any] = {
            "base_css": self._base_css,
            "version": PLUGIN_VERSION,
        }
        payload.update(data)
        return await self._renderer.render_html(template, payload)

    @staticmethod
    def _args(event: AstrMessageEvent) -> list[str]:
        """Return the arguments that follow the command name.

        Args:
            event: Incoming message event.

        Returns:
            Whitespace separated argument tokens, excluding the command itself.
        """
        tokens = (event.message_str or "").strip().split()
        return tokens[1:] if len(tokens) > 1 else []

    @staticmethod
    def _qr_png(data: str) -> bytes:
        """Render arbitrary text as a PNG QR code.

        The Skland login URL uses the ``hypergryph://`` custom scheme, so it has
        to be shown as an image rather than sent as a link.

        Args:
            data: Payload to encode.

        Returns:
            PNG image bytes.
        """
        qr = qrcode.QRCode(box_size=8, border=2)
        qr.add_data(data)
        qr.make(fit=True)
        buffer = io.BytesIO()
        qr.make_image(fill_color="black", back_color="white").save(buffer, format="PNG")
        return buffer.getvalue()

    async def _notify(self, umo: str, text: str) -> None:
        """Send a message to a session outside the current event flow.

        Args:
            umo: Unified message origin of the target session.
            text: Message text.
        """
        try:
            await self.context.send_message(umo, MessageChain([Plain(text)]))
        except Exception as exc:  # noqa: BLE001 - never let delivery break a job
            logger.warning("发送消息失败 (%s): %s", umo, exc)

    async def _resolve_binding(
        self, event: AstrMessageEvent
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        """Look up the caller's current account and primary role.

        Args:
            event: Incoming message event.

        Returns:
            Tuple of the user record and the primary binding, or ``None`` when
            the caller has no usable binding.
        """
        user = await self.store.get_user(event.get_sender_id())
        if not user or not user.get("bindings"):
            return None
        primary = str(user.get("primary_uid") or "")
        binding = next(
            (b for b in user["bindings"] if str(b.get("uid")) == primary),
            user["bindings"][0],
        )
        return user, binding

    async def _complete_binding(
        self, user_key: str, token: str, umo: str = ""
    ) -> str | None:
        """Validate a passport token and persist the resulting bindings.

        The token is exercised through the real authorization chain rather than
        the lightweight account endpoint, so a token that cannot actually read
        game data is rejected up front.

        Args:
            user_key: Platform user identifier.
            token: Hypergryph passport token.
            umo: Session that initiated the binding, stored for later pushes.

        Returns:
            A user facing error message, or ``None`` on success.
        """
        try:
            authorization = await self.skland.get_authorization(token)
            cred = await self.skland.get_credential(authorization)
            bindings = await self.skland.get_binding_list(cred)
        except SklandError as exc:
            return f"绑定失败：{exc}"
        if not bindings:
            return "该账号下没有找到明日方舟角色，请确认已在森空岛绑定角色后重试。"

        limit = int(self.config.get("max_bindings", 5) or 0)
        truncated = False
        if limit and len(bindings) > limit:
            bindings = bindings[:limit]
            truncated = True

        await self.store.upsert_auth(
            user_key,
            token,
            bindings[0].nickname,
            [binding.to_dict() for binding in bindings],
            umo=umo,
        )
        suffix = f"（仅保留前 {limit} 个）" if truncated else ""
        return f"绑定成功，共 {len(bindings)} 个明日方舟角色{suffix}。"

    # ── account commands ──────────────────────────────────────────────────

    @filter.command("方舟帮助")
    async def show_help(self, event: AstrMessageEvent):
        """Show the plugin command overview as a card."""
        image = await self._render("help.html", {"sections": HELP_SECTIONS})
        if image is None:
            yield event.plain_result(HELP_TEXT)
            return
        yield event.chain_result([Image.fromFileSystem(str(image))])

    @filter.command("方舟绑定")
    async def bind_by_qr(self, event: AstrMessageEvent):
        """Bind an account by scanning a QR code with the Skland app."""
        if not event.is_private_chat():
            yield event.plain_result("为了账号安全，请在私聊中使用绑定指令。")
            return
        user_key = event.get_sender_id()
        try:
            qr = await self.hypergryph.create_qr()
        except HypergryphError as exc:
            yield event.plain_result(f"获取二维码失败：{exc}")
            return
        if not qr["scan_id"] or not qr["scan_url"]:
            yield event.plain_result("获取二维码失败，请稍后重试。")
            return

        png = self._qr_png(qr["scan_url"])
        message_id = await self._send_qr_raw(event, png, QR_PROMPT)
        if message_id is None:
            yield event.chain_result(
                [
                    Plain(QR_PROMPT),
                    Image.fromBytes(png),
                ]
            )

        task = asyncio.create_task(
            self._poll_qr_login(
                user_key,
                qr["scan_id"],
                event.unified_msg_origin,
                event,
                message_id,
            )
        )
        self._qr_tasks.add(task)
        task.add_done_callback(self._qr_tasks.discard)

    async def _send_qr_raw(
        self, event: AstrMessageEvent, png: bytes, prompt: str
    ) -> int | None:
        """Send the QR image and its instructions through the platform client.

        Used to capture the platform message id so the QR can be recalled once it
        is no longer valid. Returns ``None`` when the platform does not support
        this, in which case the caller falls back to a normal reply.

        Args:
            event: Incoming message event.
            png: QR image bytes.
            prompt: Instruction text sent alongside the image.

        Returns:
            The platform message id, or ``None``.
        """
        try:
            if event.get_platform_name() != "aiocqhttp":
                return None
            payload = [
                {
                    "type": "image",
                    "data": {"file": f"base64://{base64.b64encode(png).decode()}"},
                },
                {"type": "text", "data": {"text": prompt}},
            ]
            group_id = event.get_group_id()
            if group_id:
                result = await event.bot.send_group_msg(
                    group_id=int(group_id), message=payload
                )
            else:
                result = await event.bot.send_private_msg(
                    user_id=int(event.get_sender_id()), message=payload
                )
            if result:
                return int(result.get("message_id"))
        except Exception as exc:  # noqa: BLE001 - fall back to a normal reply
            logger.warning("发送二维码失败，改用普通消息: %s", exc)
        return None

    async def _recall(self, event: AstrMessageEvent, message_id: int | None) -> None:
        """Best effort recall of a previously sent message.

        Args:
            event: Message event that carries the platform client.
            message_id: Platform message id; ignored when ``None``.
        """
        if not message_id or event.get_platform_name() != "aiocqhttp":
            return
        try:
            await event.bot.delete_msg(message_id=message_id)
        except Exception as exc:  # noqa: BLE001 - recall is best effort
            logger.debug("撤回消息失败 (%s): %s", message_id, exc)

    async def _poll_qr_login(
        self,
        user_key: str,
        scan_id: str,
        umo: str,
        event: AstrMessageEvent,
        message_id: int | None,
    ) -> None:
        """Poll a QR login until it is confirmed, rejected or expires.

        Args:
            user_key: Platform user identifier.
            scan_id: QR session identifier.
            umo: Session used to deliver the result.
            event: Original event, used for recalling the QR message.
            message_id: Platform message id of the QR image, if known.
        """
        deadline = time.time() + QR_TIMEOUT
        try:
            while time.time() < deadline:
                await asyncio.sleep(QR_POLL_INTERVAL)
                try:
                    scan_code = await self.hypergryph.poll_qr(scan_id)
                except HypergryphError as exc:
                    await self._notify(umo, f"扫码登录失败：{exc}")
                    return
                if not scan_code:
                    continue
                try:
                    token = await self.hypergryph.get_token_by_scan_code(scan_code)
                except HypergryphError as exc:
                    await self._notify(umo, f"扫码登录失败：{exc}")
                    return
                result = await self._complete_binding(user_key, token, umo)
                await self._notify(umo, result or "扫码绑定成功。")
                return
            await self._notify(umo, "二维码已过期，请重新发送 `方舟绑定`。")
        finally:
            await self._recall(event, message_id)

    @filter.command("方舟绑定列表")
    async def list_bindings(self, event: AstrMessageEvent):
        """List every account bound by the caller."""
        user = await self.store.get_user(event.get_sender_id())
        if not user or not user.get("bindings"):
            yield event.plain_result(NO_BINDING_TEXT)
            return
        primary = str(user.get("primary_uid") or "")
        lines = [f"共 {len(user['bindings'])} 个绑定角色："]
        for index, binding in enumerate(user["bindings"], 1):
            uid = str(binding.get("uid") or "")
            mark = " ← 当前" if uid == primary else ""
            lines.append(
                f"{index}. {binding.get('nick_name') or '未知'} · "
                f"{binding.get('channel_name') or '未知服'} · uid ...{uid[-4:]}{mark}"
            )
        lines.append("使用 `方舟切换绑定 <序号>` 或 `方舟删除绑定 <序号>` 管理。")
        yield event.plain_result("\n".join(lines))

    @filter.command("方舟切换绑定")
    async def switch_binding(self, event: AstrMessageEvent):
        """Switch the primary role used by data queries."""
        args = self._args(event)
        user = await self.store.get_user(event.get_sender_id())
        if not user or not user.get("bindings"):
            yield event.plain_result("你还没有绑定账号。")
            return
        index = self._parse_index(args[0] if args else "")
        if index is None or not 0 <= index < len(user["bindings"]):
            yield event.plain_result(
                f"序号无效。请使用 `方舟绑定列表` 查看序号（1-{len(user['bindings'])}）。"
            )
            return
        target = user["bindings"][index]
        await self.store.set_primary(event.get_sender_id(), str(target.get("uid")))
        yield event.plain_result(f"已切换到 {target.get('nick_name') or '未知角色'}。")

    @filter.command("方舟删除绑定")
    async def delete_binding(self, event: AstrMessageEvent):
        """Remove one bound role."""
        args = self._args(event)
        user = await self.store.get_user(event.get_sender_id())
        if not user or not user.get("bindings"):
            yield event.plain_result("你还没有绑定账号。")
            return
        index = self._parse_index(args[0] if args else "")
        if index is None or not 0 <= index < len(user["bindings"]):
            yield event.plain_result(
                f"序号无效。请使用 `方舟绑定列表` 查看序号（1-{len(user['bindings'])}）。"
            )
            return
        target = user["bindings"][index]
        uid = str(target.get("uid"))
        await self.store.delete_binding(event.get_sender_id(), uid)
        remaining = await self.store.get_user(event.get_sender_id())
        if not remaining:
            yield event.plain_result(
                f"已删除 {target.get('nick_name') or '该角色'}，你已没有绑定账号。"
            )
            return
        yield event.plain_result(f"已删除 {target.get('nick_name') or '该角色'}。")

    @staticmethod
    def _parse_index(raw: str) -> int | None:
        """Parse a 1-based index supplied by the user.

        Args:
            raw: Raw argument text.

        Returns:
            Zero-based index, or ``None`` when the input is not a positive int.
        """
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            return None
        return value - 1 if value >= 1 else None

    # ── data queries ──────────────────────────────────────────────────────

    async def _player_data(
        self, user: dict[str, Any], binding: dict[str, Any]
    ) -> dict[str, Any]:
        """Fetch the in-game snapshot for a role, reusing a short lived cache.

        Args:
            user: Stored user record holding the passport token.
            binding: Binding entry identifying the role.

        Returns:
            The ``data`` section of the player info response.

        Raises:
            SklandError: When the credential is rejected or the request fails.
        """
        uid = str(binding.get("uid") or "")
        ttl = int(self.config.get("data_ttl", 300) or 300)
        now = time.time()
        cached = self._player_cache.get(uid)
        if cached and cached[0] > now:
            return cached[1]
        authorization = await self.skland.get_authorization(
            str(user.get("token") or "")
        )
        cred = await self.skland.get_credential(authorization)
        data = await self.skland.get_player_info(cred, uid)
        self._player_cache[uid] = (now + ttl, data)
        return data

    async def _report_query_error(self, event: AstrMessageEvent, exc: Exception) -> str:
        """Turn a query failure into a user facing message.

        An expired credential is treated as a terminal state: the binding is
        removed so the user is asked to re-authenticate instead of hitting the
        same error forever.

        Args:
            event: Incoming message event identifying the caller.
            exc: The raised error.

        Returns:
            Message text to send back.
        """
        text = str(exc)
        if any(marker in text for marker in AUTH_ERROR_MARKERS):
            await self.store.remove_user(event.get_sender_id())
            return "账号凭证已失效，已清除你的绑定。请重新发送 `方舟绑定`。"
        return f"查询失败：{text}"

    @filter.command("方舟便签")
    async def show_note(self, event: AstrMessageEvent):
        """Show the account overview card."""
        resolved = await self._resolve_binding(event)
        if not resolved:
            yield event.plain_result(NO_BINDING_TEXT)
            return
        user, binding = resolved
        try:
            data = await self._player_data(user, binding)
        except SklandError as exc:
            yield event.plain_result(await self._report_query_error(event, exc))
            return
        note = build_note_context(data)
        image = await self._render("note.html", {"note": note})
        if image is None:
            yield event.plain_result(self._note_text(note))
            return
        yield event.chain_result([Image.fromFileSystem(str(image))])

    @staticmethod
    def _note_text(note: dict[str, Any]) -> str:
        """Build the plain text fallback for the note card.

        Args:
            note: Context produced by ``build_note_context``.

        Returns:
            Multi-line summary text.
        """
        return "\n".join(
            [
                f"{note['nickname'] or '未知博士'} · 等级 {note['level']}",
                f"入职日期：{note['register_date']}",
                f"主线进度：{note['main_stage']}",
                f"干员 / 时装：{note['char_count']} / {note['skin_count']}",
                f"理智：{note['sanity']['current']} / {note['sanity']['max']}"
                f"（{note['sanity']['remaining_text']}）",
                f"每日任务：{note['daily']['current']} / {note['daily']['total']}",
                f"每周任务：{note['weekly']['current']} / {note['weekly']['total']}",
                f"剿灭合成玉：{note['campaign']['current']} / {note['campaign']['total']}",
                f"数据时间：{note['data_time']}",
            ]
        )

    @filter.command("方舟理智")
    async def show_sanity(self, event: AstrMessageEvent):
        """Show the sanity card."""
        resolved = await self._resolve_binding(event)
        if not resolved:
            yield event.plain_result(NO_BINDING_TEXT)
            return
        user, binding = resolved
        try:
            data = await self._player_data(user, binding)
        except SklandError as exc:
            yield event.plain_result(await self._report_query_error(event, exc))
            return
        sanity = build_sanity_context(data)
        image = await self._render("sanity.html", {"sanity": sanity})
        if image is None:
            yield event.plain_result(
                f"理智：{sanity['current']} / {sanity['max']}"
                f"（{sanity['remaining_text']}）\n"
                f"数据时间：{sanity['data_time']}"
            )
            return
        yield event.chain_result([Image.fromFileSystem(str(image))])

    # ── sign-in and subscriptions ─────────────────────────────────────────

    @staticmethod
    def _to_binding(entry: dict[str, Any]) -> UserBinding:
        """Convert a stored binding record back into a ``UserBinding``.

        Args:
            entry: Stored binding dictionary.

        Returns:
            The equivalent binding object.
        """
        return UserBinding(
            uid=str(entry.get("uid") or ""),
            game_id=str(entry.get("game_id") or "1"),
            nickname=str(entry.get("nick_name") or ""),
            channel_name=str(entry.get("channel_name") or ""),
        )

    @staticmethod
    def _sign_line(binding: dict[str, Any], result: SignInResult) -> str:
        """Format one sign-in outcome for a notification.

        Args:
            binding: Stored binding dictionary.
            result: Sign-in outcome.

        Returns:
            One line of notification text.
        """
        name = str(binding.get("nick_name") or "未知角色")
        if result.success:
            awards = "、".join(result.awards) if result.awards else "无"
            return f"{name}：签到成功（{awards}）"
        return f"{name}：{result.error}"

    @filter.command("方舟签到")
    async def do_sign(self, event: AstrMessageEvent):
        """Run the Skland attendance sign-in for the current role."""
        resolved = await self._resolve_binding(event)
        if not resolved:
            yield event.plain_result(NO_BINDING_TEXT)
            return
        user, binding = resolved
        try:
            authorization = await self.skland.get_authorization(
                str(user.get("token") or "")
            )
            cred = await self.skland.get_credential(authorization)
            result = await self.skland.sign_arknights(cred, self._to_binding(binding))
        except SklandError as exc:
            yield event.plain_result(await self._report_query_error(event, exc))
            return
        if result.success:
            awards = "、".join(result.awards) if result.awards else "无"
            yield event.plain_result(f"签到成功，获得：{awards}")
        elif "已签到" in result.error or "重复" in result.error:
            yield event.plain_result("今天已经签到过了，无需重复签到。")
        else:
            yield event.plain_result(f"签到失败：{result.error}")

    @filter.command("方舟订阅理智")
    async def subscribe_sanity(self, event: AstrMessageEvent):
        """Enable sanity-full notifications for the caller."""
        if not event.is_private_chat():
            yield event.plain_result("理智提醒通过私聊推送，请在私聊中订阅。")
            return
        if not await self.store.get_user(event.get_sender_id()):
            yield event.plain_result(NO_BINDING_TEXT)
            return
        await self.store.set_sanity_sub(
            event.get_sender_id(), event.unified_msg_origin, True
        )
        minutes = max(10, int(self.config.get("sanity_poll_interval", 20) or 20))
        yield event.plain_result(
            f"已开启理智回满提醒，每 {minutes} 分钟检查一次。\n"
            "发送 `方舟取消订阅理智` 可关闭。"
        )

    @filter.command("方舟取消订阅理智")
    async def unsubscribe_sanity(self, event: AstrMessageEvent):
        """Disable sanity-full notifications for the caller."""
        await self.store.set_sanity_sub(event.get_sender_id(), "", False)
        yield event.plain_result("已关闭理智回满提醒。")

    @filter.command("方舟订阅签到")
    async def subscribe_sign(self, event: AstrMessageEvent):
        """Subscribe the current group to automatic sign-in results."""
        group_id = event.get_group_id()
        if not group_id:
            yield event.plain_result("请在群聊中使用该指令。")
            return
        await self.store.set_sign_group(group_id, event.unified_msg_origin, True)
        yield event.plain_result("已开启本群的自动签到结果通知。")

    @filter.command("方舟取消订阅签到")
    async def unsubscribe_sign(self, event: AstrMessageEvent):
        """Unsubscribe the current group from automatic sign-in results."""
        group_id = event.get_group_id()
        if not group_id:
            yield event.plain_result("请在群聊中使用该指令。")
            return
        await self.store.set_sign_group(group_id, "", False)
        yield event.plain_result("已关闭本群的自动签到通知。")

    async def _sign_in_user(
        self, user_key: str, user: dict[str, Any]
    ) -> list[tuple[dict[str, Any], SignInResult]]:
        """Sign in every role of one account.

        Args:
            user_key: Platform user identifier, used for logging.
            user: Stored user record.

        Returns:
            One ``(binding, result)`` pair per role; empty when the stored
            credential is no longer valid.
        """
        try:
            authorization = await self.skland.get_authorization(
                str(user.get("token") or "")
            )
            cred = await self.skland.get_credential(authorization)
        except SklandError as exc:
            logger.warning("[自动签到] %s 凭证失效，跳过: %s", user_key, exc)
            return []
        results: list[tuple[dict[str, Any], SignInResult]] = []
        for binding in user.get("bindings") or []:
            try:
                result = await self.skland.sign_arknights(
                    cred, self._to_binding(binding)
                )
            except SklandError as exc:
                result = SignInResult(
                    success=False,
                    nickname=str(binding.get("nick_name") or ""),
                    error=str(exc),
                )
            results.append((binding, result))
        return results

    async def _auto_sign_job(self) -> None:
        """Sign in every bound account and deliver a summary.

        Results go to the groups subscribed with ``方舟订阅签到``; when no group is
        subscribed they are sent privately to each account owner instead.
        """
        users = await self.store.all_users()
        if not users:
            return
        groups = await self.store.list_sign_groups()
        group_lines: list[str] = []
        private: dict[str, list[str]] = {}

        for user_key, user in users.items():
            results = await self._sign_in_user(user_key, user)
            for binding, result in results:
                line = self._sign_line(binding, result)
                if groups:
                    group_lines.append(line)
                else:
                    private.setdefault(user_key, []).append(line)
            # Spread requests out to avoid triggering rate limiting.
            await asyncio.sleep(3 + random.random() * 3)

        if groups and group_lines:
            text = "森空岛自动签到结果\n" + "\n".join(group_lines)
            for group in groups:
                await self._notify(str(group.get("umo") or ""), text)
            return

        for user_key, lines in private.items():
            umo = str((users.get(user_key) or {}).get("umo") or "")
            if not umo:
                continue
            await self._notify(umo, "森空岛自动签到结果\n" + "\n".join(lines))

    async def _sanity_poll_job(self) -> None:
        """Notify subscribers whose sanity has just reached the cap.

        Each subscriber is notified at most once per fill-up; the flag resets as
        soon as sanity drops below the cap again.
        """
        for sub in await self.store.list_sanity_subs():
            user_key = str(sub.get("user_key") or "")
            umo = str(sub.get("umo") or "")
            user = await self.store.get_user(user_key)
            if not user or not umo:
                continue
            bindings = user.get("bindings") or []
            binding = next(
                (
                    b
                    for b in bindings
                    if str(b.get("uid")) == str(user.get("primary_uid"))
                ),
                bindings[0] if bindings else None,
            )
            if not binding:
                continue
            try:
                data = await self._player_data(user, binding)
            except SklandError as exc:
                logger.warning("[理智轮询] %s 查询失败: %s", user_key, exc)
                continue

            sanity = build_sanity_context(data)
            if sanity["full"]:
                if self._sanity_notified.get(user_key):
                    continue
                self._sanity_notified[user_key] = True
                await self._notify(
                    umo,
                    f"理智已回满（{sanity['current']} / {sanity['max']}），记得清体力。",
                )
            else:
                self._sanity_notified[user_key] = False
            await asyncio.sleep(3 + random.random() * 3)

    # ── operator queries ──────────────────────────────────────────────────

    @filter.command("方舟干员列表")
    async def show_roster(self, event: AstrMessageEvent):
        """Show the owned-operator roster card."""
        resolved = await self._resolve_binding(event)
        if not resolved:
            yield event.plain_result(NO_BINDING_TEXT)
            return
        user, binding = resolved
        try:
            data = await self._player_data(user, binding)
        except SklandError as exc:
            yield event.plain_result(await self._report_query_error(event, exc))
            return
        char_info = data.get("charInfoMap") or {}
        groups = group_operators(data.get("chars") or [], char_info)
        roster = build_roster_context(groups, char_info)
        image = await self._render("operator_list.html", {"roster": roster})
        if image is None:
            summary = "、".join(
                f"{group['profession_cn']} {len(group['operators'])}"
                for group in groups
            )
            yield event.plain_result(
                f"已持有干员 {roster['owned']} / {roster['total']}。\n{summary}"
            )
            return
        yield event.chain_result([Image.fromFileSystem(str(image))])

    @filter.command("方舟干员", alias={"方舟面板"})
    async def show_operator(self, event: AstrMessageEvent):
        """Show the detail card for one owned operator."""
        args = self._args(event)
        if not args:
            yield event.plain_result(
                "用法：方舟干员 <干员名>\n"
                "例如：方舟干员 阿米娅\n"
                "发送 `方舟干员列表` 可查看已持有的干员。"
            )
            return
        name = " ".join(args).strip()
        resolved = await self._resolve_binding(event)
        if not resolved:
            yield event.plain_result(NO_BINDING_TEXT)
            return
        user, binding = resolved
        try:
            data = await self._player_data(user, binding)
        except SklandError as exc:
            yield event.plain_result(await self._report_query_error(event, exc))
            return
        operator = find_operator(
            data.get("chars") or [], data.get("charInfoMap") or {}, name
        )
        if operator is None:
            yield event.plain_result(
                f"未找到干员「{name}」。发送 `方舟干员列表` 可查看已持有的干员。"
            )
            return
        context = build_operator_context(operator, data.get("equipmentInfoMap") or {})
        image = await self._render("operator.html", {"op": context})
        if image is None:
            yield event.plain_result(self._operator_text(context))
            return
        yield event.chain_result([Image.fromFileSystem(str(image))])

    @staticmethod
    def _operator_text(context: dict[str, Any]) -> str:
        """Build the plain text fallback for the operator card.

        Args:
            context: Context produced by ``build_operator_context``.

        Returns:
            Multi-line summary text.
        """
        lines = [
            f"{context['name']} {'★' * context['stars']} · {context['profession_cn']}",
            f"等级 {context['level']} · 精英 {context['elite']} · "
            f"潜能 {context['potential']} · 信赖 {context['favor']}%",
        ]
        if context["skills"]:
            lines.append(
                "技能："
                + "、".join(
                    f"{index} "
                    + (
                        f"专精{skill['specialize']}"
                        if skill["specialize"]
                        else "未专精"
                    )
                    for index, skill in enumerate(context["skills"], 1)
                )
            )
        if context["equips"]:
            lines.append(
                "模组："
                + "、".join(
                    f"{equip['name']} Lv.{equip['level']}"
                    for equip in context["equips"]
                )
            )
        return "\n".join(lines)

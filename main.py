"""AstrBot entry point for the Arknights (罗德岛终端) plugin.

This is the only module that touches the AstrBot framework; every protocol
detail lives under ``core/`` so it can be unit tested without the framework.
"""

from __future__ import annotations

import asyncio
import base64
import io
import time
from pathlib import Path
from typing import Any

import qrcode
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Image, Plain
from astrbot.api.star import Context, Star, register
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from .core.hypergryph import HypergryphClient, HypergryphError
from .core.render import Renderer
from .core.skland import SklandClient, SklandError
from .core.store import Store

PLUGIN_NAME = "astrbot_plugin_arknights"
PLUGIN_VERSION = "0.1.0"

# Seconds the QR code stays valid, and how often it is polled.
QR_TIMEOUT = 120
QR_POLL_INTERVAL = 2

HELP_TEXT = """罗德岛终端 · 明日方舟助手

【账号绑定】（请私聊使用）
扫码绑定              使用森空岛 APP 扫码登录
验证码绑定 <手机号>    发送短信验证码
验证码绑定 <手机号> <验证码>  完成绑定
token绑定 <token>     使用鹰角通行证 token 绑定
绑定列表              查看所有绑定账号
切换绑定 <序号>        切换主账号
删除绑定 <序号>        解绑指定账号

【数据查询】
便签                  账号总览
理智                  理智与回满时间
干员列表              已持有干员图鉴
<干员名>面板           单个干员详情

【签到与提醒】
签到                  手动执行森空岛签到
订阅理智 / 取消订阅理智  理智回满推送
订阅签到 / 取消订阅签到  群内签到结果通知

账号凭证仅保存在本机，且不会在任何回复中回显。
"""

# Structured copy of HELP_TEXT used by the rendered help card.
HELP_SECTIONS = [
    {
        "title": "账号绑定（请私聊使用）",
        "items": [
            {"cmd": "扫码绑定", "desc": "使用森空岛 APP 扫码登录"},
            {"cmd": "验证码绑定 <手机号>", "desc": "发送短信验证码"},
            {"cmd": "验证码绑定 <手机号> <验证码>", "desc": "完成绑定"},
            {"cmd": "token绑定 <token>", "desc": "使用鹰角通行证 token 绑定"},
            {"cmd": "绑定列表", "desc": "查看所有绑定账号"},
            {"cmd": "切换绑定 <序号>", "desc": "切换主账号"},
            {"cmd": "删除绑定 <序号>", "desc": "解绑指定账号"},
        ],
    },
    {
        "title": "数据查询",
        "items": [
            {"cmd": "便签", "desc": "账号总览"},
            {"cmd": "理智", "desc": "理智与回满时间"},
            {"cmd": "干员列表", "desc": "已持有干员图鉴"},
            {"cmd": "<干员名>面板", "desc": "单个干员详情"},
        ],
    },
    {
        "title": "签到与提醒",
        "items": [
            {"cmd": "签到", "desc": "手动执行森空岛签到"},
            {"cmd": "订阅理智 / 取消订阅理智", "desc": "理智回满推送"},
            {"cmd": "订阅签到 / 取消订阅签到", "desc": "群内签到结果通知"},
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

    async def terminate(self) -> None:
        """Release network resources and cancel background tasks."""
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

    async def _complete_binding(self, user_key: str, token: str) -> str | None:
        """Validate a passport token and persist the resulting bindings.

        The token is exercised through the real authorization chain rather than
        the lightweight account endpoint, so a token that cannot actually read
        game data is rejected up front.

        Args:
            user_key: Platform user identifier.
            token: Hypergryph passport token.

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
        )
        suffix = f"（仅保留前 {limit} 个）" if truncated else ""
        return f"绑定成功，共 {len(bindings)} 个明日方舟角色{suffix}。"

    # ── account commands ──────────────────────────────────────────────────

    @filter.command("ark", alias={"方舟帮助", "ark帮助"})
    async def show_help(self, event: AstrMessageEvent):
        """Show the plugin command overview as a card."""
        image = await self._render("help.html", {"sections": HELP_SECTIONS})
        if image is None:
            yield event.plain_result(HELP_TEXT)
            return
        yield event.chain_result([Image.fromFileSystem(str(image))])

    @filter.command("扫码绑定")
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
        message_id = await self._send_qr_raw(event, png)
        if message_id is None:
            yield event.chain_result(
                [
                    Plain(f"请使用森空岛 APP 扫码登录（{QR_TIMEOUT} 秒内有效）："),
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

    async def _send_qr_raw(self, event: AstrMessageEvent, png: bytes) -> int | None:
        """Send the QR image directly through the platform client.

        Used to capture the platform message id so the QR can be recalled once it
        is no longer valid. Returns ``None`` when the platform does not support
        this, in which case the caller falls back to a normal reply.

        Args:
            event: Incoming message event.
            png: QR image bytes.

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
                }
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
                result = await self._complete_binding(user_key, token)
                await self._notify(umo, result or "扫码绑定成功。")
                return
            await self._notify(umo, "二维码已过期，请重新发送 `扫码绑定`。")
        finally:
            await self._recall(event, message_id)

    @filter.command("验证码绑定")
    async def bind_by_phone(self, event: AstrMessageEvent):
        """Bind an account with an SMS verification code."""
        if not event.is_private_chat():
            yield event.plain_result("为了账号安全，请在私聊中使用绑定指令。")
            return
        args = self._args(event)
        if not args:
            yield event.plain_result(
                "用法：\n验证码绑定 <手机号>  —— 发送验证码\n"
                "验证码绑定 <手机号> <验证码>  —— 完成绑定"
            )
            return
        phone = args[0]
        if len(args) < 2:
            try:
                await self.hypergryph.send_phone_code(phone)
            except HypergryphError as exc:
                yield event.plain_result(f"发送验证码失败：{exc}")
                return
            yield event.plain_result(
                f"验证码已发送至 {phone}，请回复：验证码绑定 {phone} <验证码>"
            )
            return

        try:
            token = await self.hypergryph.login_by_phone_code(phone, args[1])
        except HypergryphError as exc:
            yield event.plain_result(f"验证码登录失败：{exc}")
            return
        result = await self._complete_binding(event.get_sender_id(), token)
        yield event.plain_result(result or "绑定成功。")

    @filter.command("token绑定", alias={"Token绑定", "tok绑定"})
    async def bind_by_token(self, event: AstrMessageEvent):
        """Bind an account with a pasted Hypergryph passport token."""
        if not event.is_private_chat():
            yield event.plain_result("为了账号安全，请在私聊中使用绑定指令。")
            return
        args = self._args(event)
        if not args:
            yield event.plain_result(
                "用法：token绑定 <token>\n"
                "token 获取方式：登录森空岛后访问 https://web-api.skland.com/account/info/hg"
            )
            return
        result = await self._complete_binding(event.get_sender_id(), args[0].strip())
        yield event.plain_result(result or "绑定成功。")

    @filter.command("绑定列表")
    async def list_bindings(self, event: AstrMessageEvent):
        """List every account bound by the caller."""
        user = await self.store.get_user(event.get_sender_id())
        if not user or not user.get("bindings"):
            yield event.plain_result(
                "你还没有绑定账号。可私聊发送 `扫码绑定` 或 `token绑定 <token>` 开始绑定。"
            )
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
        lines.append("使用 `切换绑定 <序号>` 或 `删除绑定 <序号>` 管理。")
        yield event.plain_result("\n".join(lines))

    @filter.command("切换绑定")
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
                f"序号无效。请使用 `绑定列表` 查看序号（1-{len(user['bindings'])}）。"
            )
            return
        target = user["bindings"][index]
        await self.store.set_primary(event.get_sender_id(), str(target.get("uid")))
        yield event.plain_result(f"已切换到 {target.get('nick_name') or '未知角色'}。")

    @filter.command("删除绑定")
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
                f"序号无效。请使用 `绑定列表` 查看序号（1-{len(user['bindings'])}）。"
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

"""Arknights headhunting record import and analysis.

Importing records requires chaining four credentials, all derived from the
Hypergryph passport token obtained by scanning the login QR code:

1. ``oauth2/v2/grant`` with the ``arknights`` app code yields a grant token.
2. ``u8_token_by_uid`` exchanges the grant token for a per-role token.
3. ``ak.hypergryph.com/user/api/role/login`` yields the ``ak-user-center`` cookie.
4. ``inquiry/gacha/cate`` and ``inquiry/gacha/history`` then return the records,
   authenticated by ``X-Account-Token`` (the passport token) plus
   ``X-Role-Token`` (the role token) and that cookie.

The analysis half is pure and unit tested; only :class:`GachaClient` touches the
network.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from astrbot.api import logger

from .assets import char_avatar, char_portrait
from .gamedata import banner_group

AS_BASE = "https://as.hypergryph.com"
BINDING_BASE = "https://binding-api-account-prod.hypergryph.com"
AK_BASE = "https://ak.hypergryph.com"

# App code used by the web headhunting page.
GRANT_APP_CODE = "be36d44aa36bfb5b"

# Used when the category endpoint is unavailable.
FALLBACK_CATEGORIES = ("normal", "classic", "anniver_fest", "summer_fest", "mujica")

SIX_STAR = 6
PAGE_SIZE = 100
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)


class GachaError(Exception):
    """Raised when a headhunting record request fails."""


def _web_headers(**extra: str) -> dict[str, str]:
    """Build browser-like headers for the Arknights web endpoints.

    Args:
        **extra: Additional headers.

    Returns:
        Header mapping.
    """
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": AK_BASE,
        "Referer": f"{AK_BASE}/user/headhunting",
        "User-Agent": USER_AGENT,
    }
    headers.update(extra)
    return headers


class GachaClient:
    """Fetches Arknights headhunting records for one role."""

    def __init__(
        self,
        base_url_overrides: dict[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize the client.

        Args:
            base_url_overrides: Optional ``as`` / ``binding`` / ``ak`` overrides.
            client: Optional pre-built HTTP client, used by tests.
        """
        overrides = base_url_overrides or {}
        self.as_base = overrides.get("as", AS_BASE)
        self.binding_base = overrides.get("binding", BINDING_BASE)
        self.ak_base = overrides.get("ak", AK_BASE)
        self._client = client
        self._owns_client = client is None

    async def close(self) -> None:
        """Release the HTTP client when this instance created it."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        """Return the shared HTTP client, creating it on first use."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
            self._owns_client = True
        return self._client

    async def _post_json(
        self, url: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> httpx.Response:
        """POST a JSON body and return the raw response.

        Args:
            url: Absolute URL.
            payload: JSON body.
            headers: Request headers.

        Returns:
            The HTTP response.

        Raises:
            GachaError: On transport failure.
        """
        try:
            return await self._get_client().post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise GachaError(f"请求失败: {exc}") from exc

    async def grant_token(self, passport_token: str) -> str:
        """Exchange a passport token for a grant token.

        Args:
            passport_token: Hypergryph passport token from the QR login.

        Returns:
            The grant token.

        Raises:
            GachaError: When the exchange is rejected.
        """
        response = await self._post_json(
            f"{self.as_base}/user/oauth2/v2/grant",
            {"token": passport_token, "appCode": GRANT_APP_CODE, "type": 1},
            _web_headers(),
        )
        try:
            data = response.json()
        except ValueError as exc:
            raise GachaError("授权响应格式异常") from exc
        if not isinstance(data, dict) or data.get("status") != 0:
            raise GachaError("账号凭证已失效，请重新执行 `ark绑定`")
        return str((data.get("data") or {}).get("token") or "")

    async def role_token(self, grant: str, uid: str) -> str:
        """Exchange a grant token for a per-role token.

        Args:
            grant: Grant token.
            uid: Role uid.

        Returns:
            The role (u8) token.

        Raises:
            GachaError: When the exchange is rejected.
        """
        response = await self._post_json(
            f"{self.binding_base}/account/binding/v1/u8_token_by_uid",
            {"token": grant, "uid": uid},
            _web_headers(),
        )
        try:
            data = response.json()
        except ValueError as exc:
            raise GachaError("角色令牌响应格式异常") from exc
        token = str((data.get("data") or {}).get("token") or "")
        if not token:
            message = data.get("message") or data.get("msg") or "获取角色令牌失败"
            raise GachaError(str(message))
        return token

    async def center_cookie(self, role_token: str) -> str:
        """Log in to the web console and read the session cookie.

        Args:
            role_token: Per-role token.

        Returns:
            The ``ak-user-center`` cookie value.

        Raises:
            GachaError: When the login does not return a cookie.
        """
        response = await self._post_json(
            f"{self.ak_base}/user/api/role/login",
            {"token": role_token, "source_from": "", "share_type": "", "share_by": ""},
            _web_headers(),
        )
        cookie = response.cookies.get("ak-user-center")
        if not cookie:
            raise GachaError("登录抽卡页面失败，请稍后重试")
        return cookie

    def _record_headers(
        self, passport_token: str, role_token: str, cookie: str = ""
    ) -> dict[str, str]:
        """Build the headers required by the inquiry endpoints.

        Args:
            passport_token: Passport token sent as ``X-Account-Token``.
            role_token: Role token sent as ``X-Role-Token``.
            cookie: Session cookie forwarded explicitly, rather than through
                httpx's deprecated per-request cookie handling.

        Returns:
            Header mapping.
        """
        headers = _web_headers(
            **{"X-Account-Token": passport_token, "X-Role-Token": role_token}
        )
        if cookie:
            headers["Cookie"] = f"ak-user-center={cookie}"
        return headers

    async def categories(
        self, uid: str, passport_token: str, role_token: str, cookie: str
    ) -> list[str]:
        """List the available gacha categories.

        Args:
            uid: Role uid.
            passport_token: Passport token.
            role_token: Role token.
            cookie: ``ak-user-center`` cookie.

        Returns:
            Category identifiers; the known list is used when the endpoint does
            not answer usefully.
        """
        url = f"{self.ak_base}/user/api/inquiry/gacha/cate"
        try:
            response = await self._get_client().get(
                url,
                params={"uid": uid},
                headers=self._record_headers(passport_token, role_token, cookie),
            )
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("获取抽卡类别失败，使用内置列表: %s", exc)
            return list(FALLBACK_CATEGORIES)
        found: list[str] = []
        if isinstance(data, dict) and data.get("code") == 0:
            for item in data.get("data") or []:
                if isinstance(item, dict):
                    value = item.get("id") or item.get("cateId")
                else:
                    value = item
                if value:
                    found.append(str(value))
        return found or list(FALLBACK_CATEGORIES)

    async def history_page(
        self,
        uid: str,
        category: str,
        passport_token: str,
        role_token: str,
        cookie: str,
        gacha_ts: str | None = None,
        pos: int | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Fetch one page of headhunting records.

        Args:
            uid: Role uid.
            category: Category identifier.
            passport_token: Passport token.
            role_token: Role token.
            cookie: ``ak-user-center`` cookie.
            gacha_ts: Exclusive cursor timestamp from the previous page.
            pos: Exclusive cursor position from the previous page.

        Returns:
            Tuple of the record list and whether more pages may follow.

        Raises:
            GachaError: When the request fails outright.
        """
        params: dict[str, Any] = {
            "uid": uid,
            "category": category,
            "size": PAGE_SIZE,
        }
        if gacha_ts:
            params["gachaTs"] = gacha_ts
        if pos is not None:
            params["pos"] = pos
        try:
            response = await self._get_client().get(
                f"{self.ak_base}/user/api/inquiry/gacha/history",
                params=params,
                headers=self._record_headers(passport_token, role_token, cookie),
            )
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise GachaError(f"获取抽卡记录失败: {exc}") from exc
        if not isinstance(data, dict) or data.get("code") != 0:
            message = (data or {}).get("message") if isinstance(data, dict) else None
            raise GachaError(str(message or "获取抽卡记录失败"))
        payload = data.get("data") or {}
        records = payload.get("list") or payload.get("gachaList") or []
        return [item for item in records if isinstance(item, dict)], len(
            records
        ) >= PAGE_SIZE

    async def fetch_records(
        self, passport_token: str, uid: str, max_pages: int = 20
    ) -> list[dict[str, Any]]:
        """Fetch every headhunting record for a role.

        Args:
            passport_token: Hypergryph passport token.
            uid: Role uid.
            max_pages: Safety cap on pages per category.

        Returns:
            Deduplicated records, newest first.

        Raises:
            GachaError: When the credential chain fails.
        """
        grant = await self.grant_token(passport_token)
        role = await self.role_token(grant, uid)
        cookie = await self.center_cookie(role)
        categories = await self.categories(uid, passport_token, role, cookie)

        # The cursor pair is only unique within one category: two categories can
        # legitimately report the same (gachaTs, pos), so the category has to be
        # part of the key or genuine pulls get silently dropped and every
        # statistic downstream under-counts.
        collected: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
        for category in categories:
            gacha_ts: str | None = None
            pos: int | None = None
            for _ in range(max_pages):
                page, more = await self.history_page(
                    uid, category, passport_token, role, cookie, gacha_ts, pos
                )
                for record in page:
                    item = dict(record)
                    item["category"] = category
                    key = (category, record.get("gachaTs"), record.get("pos"))
                    collected.setdefault(key, item)
                if not more or not page:
                    break
                last = page[-1]
                gacha_ts = str(last.get("gachaTs") or "")
                pos = last.get("pos")
                if not gacha_ts and pos is None:
                    break

        records = list(collected.values())
        records.sort(
            key=lambda item: (int(item.get("gachaTs") or 0), int(item.get("pos") or 0)),
            reverse=True,
        )
        return records


def format_record_time(gacha_ts: Any) -> str:
    """Format a record timestamp.

    Args:
        gacha_ts: Unix timestamp in seconds.

    Returns:
        ``MM-DD HH:MM``, or an empty string when the value is unusable.
    """
    try:
        seconds = int(gacha_ts or 0)
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return ""
    try:
        return datetime.fromtimestamp(seconds).strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return ""


def _stars(record: dict[str, Any]) -> int:
    """Resolve the star rating of a record.

    The API reports rarity zero based (2 == three star). A missing or malformed
    value falls back to the gacha floor so a corrupt record cannot invent a
    phantom one-star bucket.

    Args:
        record: Raw gacha record.

    Returns:
        Star rating clamped to ``[3, 6]``.
    """
    try:
        rarity = int(record.get("rarity"))
    except (TypeError, ValueError):
        rarity = 2
    return max(3, min(6, rarity + 1))


def _six_star_identity(
    record: dict[str, Any], char_info: dict[str, Any]
) -> tuple[str, str]:
    """Resolve a six-star record into its id and display name.

    Args:
        record: Raw gacha record.
        char_info: ``charInfoMap`` used to name operators the record omits.

    Returns:
        Tuple of operator id and display name.
    """
    char_id = str(record.get("charId") or "")
    name = str(record.get("charName") or "")
    if not name:
        name = str((char_info.get(char_id) or {}).get("name") or char_id)
    return char_id, name


def _luck_label(avg_six: float, six_total: int) -> str:
    """Describe how lucky a banner was.

    Args:
        avg_six: Average pulls per six star.
        six_total: Number of six stars observed.

    Returns:
        A short rating, or an empty string when there is nothing to rate.
    """
    if six_total <= 0 or avg_six <= 0:
        return ""
    # Calibrated against the real odds: a 2% base rate with soft pity from pull
    # 50 puts the expected average at roughly 34-35 pulls per six star.
    if avg_six <= 25:
        return "欧皇"
    if avg_six <= 32:
        return "偏欧"
    if avg_six <= 42:
        return "平稳"
    if avg_six <= 50:
        return "偏非"
    return "非酋"


def _summarize(
    records: list[dict[str, Any]],
    gamedata: Any,
    char_info: dict[str, Any],
    recent_limit: int,
) -> dict[str, Any]:
    """Summarize one set of records ordered oldest first.

    The six-star sequence and the pity counter are computed over exactly the
    records passed in, so callers must not mix banner families: pity is tracked
    per banner family in game, and merging families produced the wrong averages
    that made special banners look broken.

    Args:
        records: Records ordered oldest first.
        gamedata: Optional :class:`~core.gamedata.GameData`.
        char_info: ``charInfoMap`` for name resolution.
        recent_limit: How many recent six stars to keep.

    Returns:
        Statistics mapping for this record set.
    """
    counts = {SIX_STAR: 0, 5: 0, 4: 0, 3: 0}
    six_stars: list[dict[str, Any]] = []
    pools: dict[str, dict[str, Any]] = {}
    since = 0
    up_hits = 0
    off_rate = 0
    up_known = False

    for record in records:
        stars = _stars(record)
        counts[stars] = counts.get(stars, 0) + 1
        since += 1

        pool_id = str(record.get("poolId") or "")
        pool_name = str(record.get("poolName") or "")
        if gamedata is not None:
            pool_name = gamedata.pool_name(pool_id) or pool_name
        pool = pools.setdefault(
            pool_id or pool_name,
            {"name": pool_name or pool_id, "count": 0, "six": 0, "five": 0},
        )
        pool["count"] += 1
        if stars == SIX_STAR:
            pool["six"] += 1
        elif stars == 5:
            pool["five"] += 1

        if stars == SIX_STAR:
            char_id, name = _six_star_identity(record, char_info)
            up_list = list(gamedata.up_six(pool_id)) if gamedata is not None else []
            if up_list:
                up_known = True
                is_up: bool | None = char_id in up_list
            else:
                # No rate-up data for this pool: report the pull without
                # claiming either way rather than counting a false off-rate.
                is_up = None
            if is_up is True:
                up_hits += 1
            elif is_up is False:
                off_rate += 1
            six_stars.append(
                {
                    "char_id": char_id,
                    "name": name,
                    "stars": SIX_STAR,
                    "avatar": char_avatar(char_id) if char_id else "",
                    "portrait": char_portrait(char_id, 2) if char_id else "",
                    "pulls": since,
                    "pool_id": pool_id,
                    "pool_name": pool_name,
                    "is_up": is_up,
                    "time_text": format_record_time(record.get("gachaTs")),
                    "is_new": bool(record.get("isNew")),
                }
            )
            since = 0

    total = len(records)
    six_total = counts[SIX_STAR]
    stamps = [
        int(item.get("gachaTs") or 0)
        for item in records
        if int(item.get("gachaTs") or 0) > 0
    ]
    date_range = ""
    if stamps:
        date_range = (
            f"{format_record_time(min(stamps))} ~ {format_record_time(max(stamps))}"
        )
    return {
        "date_range": date_range,
        "avg_up": round(total / up_hits, 1) if up_hits else 0.0,
        "total": total,
        "counts": counts,
        "six_total": six_total,
        "five_total": counts.get(5, 0),
        "avg_six": round(total / six_total, 1) if six_total else 0.0,
        "pity": since,
        "up_hits": up_hits,
        "off_rate": off_rate,
        "up_known": up_known,
        "six_stars": list(reversed(six_stars))[:recent_limit],
        "six_stars_total": len(six_stars),
        "pools": sorted(pools.values(), key=lambda item: item["count"], reverse=True),
    }


def analyze(
    records: list[dict[str, Any]],
    gamedata: Any = None,
    char_info: dict[str, Any] | None = None,
    recent_limit: int = 12,
) -> dict[str, Any]:
    """Compute headhunting statistics, overall and per banner family.

    Records are split by banner family first and summarized independently, then
    summarized once more as a whole. The per-family figures are the meaningful
    ones for pity and average pulls; the overall figures are kept for the card
    header.

    Args:
        records: Records as returned by :meth:`GachaClient.fetch_records`.
        gamedata: Optional :class:`~core.gamedata.GameData` for pool and UP names.
        char_info: Optional ``charInfoMap`` used to resolve operator names.
        recent_limit: How many recent six stars to include per section.

    Returns:
        Analysis context for ``gacha.html``.
    """
    char_info = char_info or {}
    ordered = sorted(
        records or [],
        key=lambda item: (int(item.get("gachaTs") or 0), int(item.get("pos") or 0)),
    )

    families: dict[str, dict[str, Any]] = {}
    for record in ordered:
        key, label = banner_group(str(record.get("poolId") or ""))
        bucket = families.setdefault(key, {"label": label, "records": []})
        bucket["records"].append(record)

    context = _summarize(ordered, gamedata, char_info, recent_limit)
    context["luck"] = _luck_label(context["avg_six"], context["six_total"])

    banners = []
    for key, bucket in families.items():
        summary = _summarize(bucket["records"], gamedata, char_info, recent_limit)
        summary["key"] = key
        summary["label"] = bucket["label"]
        summary["luck"] = _luck_label(summary["avg_six"], summary["six_total"])
        summary["newest"] = max(
            (int(item.get("gachaTs") or 0) for item in bucket["records"]), default=0
        )
        banners.append(summary)
    banners.sort(key=lambda item: item["newest"], reverse=True)

    context["banners"] = banners
    context["banner_count"] = len(banners)
    return context

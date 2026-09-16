"""Skland (森空岛) protocol client.

The module is split in two halves:

* Protocol primitives (device fingerprint construction, request signing and
  sanity extrapolation) implemented as pure functions so they can be unit
  tested without network access.
* :class:`SklandClient`, which performs the actual HTTP calls.

Nothing here imports ``astrbot``; the framework only appears in ``main.py``.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import hmac
import json
import logging
import math
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from Crypto.Cipher import AES, DES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import pad

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 12; SM-A5560 Build/V417IR; wv) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Version/4.0 Chrome/101.0.4951.61 Safari/537.36; SKLand/1.52.1"
)
LOGIN_USER_AGENT = (
    "Skland/1.0.1 (com.hypergryph.skland; build:100001014; Android 31; ) Okhttp/4.11.0"
)

APP_CODE = "4ca99fa6b56cc2ba"
SANITY_SECONDS_PER_POINT = 360

# Protocol constant: browser fingerprint fields and their obfuscation rules.
DES_RULE: dict[str, dict[str, Any]] = {
    "appId": {
        "cipher": "DES",
        "is_encrypt": 1,
        "key": "uy7mzc4h",
        "obfuscated_name": "xx",
    },
    "box": {"is_encrypt": 0, "obfuscated_name": "jf"},
    "canvas": {
        "cipher": "DES",
        "is_encrypt": 1,
        "key": "snrn887t",
        "obfuscated_name": "yk",
    },
    "clientSize": {
        "cipher": "DES",
        "is_encrypt": 1,
        "key": "cpmjjgsu",
        "obfuscated_name": "zx",
    },
    "organization": {
        "cipher": "DES",
        "is_encrypt": 1,
        "key": "78moqjfc",
        "obfuscated_name": "dp",
    },
    "os": {
        "cipher": "DES",
        "is_encrypt": 1,
        "key": "je6vk6t4",
        "obfuscated_name": "pj",
    },
    "platform": {
        "cipher": "DES",
        "is_encrypt": 1,
        "key": "pakxhcd2",
        "obfuscated_name": "gm",
    },
    "plugins": {
        "cipher": "DES",
        "is_encrypt": 1,
        "key": "v51m3pzl",
        "obfuscated_name": "kq",
    },
    "pmf": {
        "cipher": "DES",
        "is_encrypt": 1,
        "key": "2mdeslu3",
        "obfuscated_name": "vw",
    },
    "protocol": {"is_encrypt": 0, "obfuscated_name": "protocol"},
    "referer": {
        "cipher": "DES",
        "is_encrypt": 1,
        "key": "y7bmrjlc",
        "obfuscated_name": "ab",
    },
    "res": {
        "cipher": "DES",
        "is_encrypt": 1,
        "key": "whxqm2a7",
        "obfuscated_name": "hf",
    },
    "rtype": {
        "cipher": "DES",
        "is_encrypt": 1,
        "key": "x8o2h2bl",
        "obfuscated_name": "lo",
    },
    "sdkver": {
        "cipher": "DES",
        "is_encrypt": 1,
        "key": "9q3dcxp2",
        "obfuscated_name": "sc",
    },
    "status": {
        "cipher": "DES",
        "is_encrypt": 1,
        "key": "2jbrxxw4",
        "obfuscated_name": "an",
    },
    "subVersion": {
        "cipher": "DES",
        "is_encrypt": 1,
        "key": "eo3i2puh",
        "obfuscated_name": "ns",
    },
    "svm": {
        "cipher": "DES",
        "is_encrypt": 1,
        "key": "fzj3kaeh",
        "obfuscated_name": "qr",
    },
    "time": {
        "cipher": "DES",
        "is_encrypt": 1,
        "key": "q2t3odsk",
        "obfuscated_name": "nb",
    },
    "timezone": {
        "cipher": "DES",
        "is_encrypt": 1,
        "key": "1uv05lj5",
        "obfuscated_name": "as",
    },
    "tn": {
        "cipher": "DES",
        "is_encrypt": 1,
        "key": "x9nzj1bp",
        "obfuscated_name": "py",
    },
    "trees": {
        "cipher": "DES",
        "is_encrypt": 1,
        "key": "acfs0xo4",
        "obfuscated_name": "pi",
    },
    "ua": {
        "cipher": "DES",
        "is_encrypt": 1,
        "key": "k92crp1t",
        "obfuscated_name": "bj",
    },
    "url": {
        "cipher": "DES",
        "is_encrypt": 1,
        "key": "y95hjkoo",
        "obfuscated_name": "cf",
    },
    "version": {"is_encrypt": 0, "obfuscated_name": "version"},
    "vpw": {
        "cipher": "DES",
        "is_encrypt": 1,
        "key": "r9924ab5",
        "obfuscated_name": "ca",
    },
}

DES_TARGET: dict[str, Any] = {
    "protocol": 102,
    "organization": "UWXspnCCJN4sfYlNfqps",
    "appId": "default",
    "os": "web",
    "version": "3.0.0",
    "sdkver": "3.0.0",
    "box": "",
    "rtype": "all",
    "subVersion": "1.0.0",
    "time": 0,
}

BROWSER_ENV: dict[str, Any] = {
    "plugins": (
        "MicrosoftEdgePDFPluginPortableDocumentFormatinternal-pdf-viewer1,"
        "MicrosoftEdgePDFViewermhjfbmdgcfjbbpaeojofohoefgiehjai1"
    ),
    "ua": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0"
    ),
    "canvas": "259ffe69",
    "timezone": -480,
    "platform": "Win32",
    "url": "https://www.skland.com/",
    "referer": "",
    "res": "1920_1080_24_1.25",
    "clientSize": "0_0_1080_1920_1920_1080_1920_1080",
    "status": "0011",
}

RSA_PUBLIC_KEY = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCmxMNr7n8ZeT0tE1R9j/mPixoinPkeM+k4"
    "VGIn/s0k7N5rJAfnZ0eMER+QhwFvshzo0LNmeUkpR8uIlU/GEVr8mN28sKmwd2gpygqj0ePn"
    "BmOW4v0ZVwbSYK+izkhVFk2V/doLoMbWy6b+UnA8mkjvg0iYWRByfRsK2gdl7llqCwIDAQAB"
)

FP_BASE = "https://fp-it.portal101.cn"
AS_BASE = "https://as.hypergryph.com"
ZONAI_BASE = "https://zonai.skland.com"


class SklandError(Exception):
    """Raised when a Skland request fails."""


@dataclass
class Credential:
    """Skland credential pair used to sign API requests."""

    token: str
    cred: str


@dataclass
class UserBinding:
    """A single Arknights role bound to a Skland account."""

    uid: str
    game_id: str = "1"
    nickname: str = ""
    channel_name: str = ""

    def to_dict(self) -> dict[str, str]:
        """Serialize the binding for persistence."""
        return {
            "uid": self.uid,
            "game_id": self.game_id,
            "nick_name": self.nickname,
            "channel_name": self.channel_name,
        }


@dataclass
class SignInResult:
    """Outcome of a sign-in attempt."""

    success: bool
    nickname: str = ""
    awards: list[str] = field(default_factory=list)
    error: str = ""


def des_encrypt(key: bytes, data: bytes) -> bytes:
    """Encrypt bytes with single DES in ECB mode using null padding.

    Args:
        key: DES key; truncated or null-extended to 8 bytes.
        data: Plaintext bytes.

    Returns:
        Ciphertext bytes.
    """
    padding_len = 8 - (len(data) % 8)
    padded = data + (b"\x00" * padding_len)
    key_8 = key[:8].ljust(8, b"\x00")
    cipher = DES.new(key_8, DES.MODE_ECB)
    return b"".join(cipher.encrypt(padded[i : i + 8]) for i in range(0, len(padded), 8))


def apply_des_rules(data: dict[str, Any]) -> dict[str, Any]:
    """Apply the fingerprint obfuscation rules to a payload.

    Each key is renamed to its obfuscated name; keys flagged for encryption are
    DES encrypted and base64 encoded first.

    Args:
        data: Fingerprint payload keyed by plain field names.

    Returns:
        Payload keyed by obfuscated field names.
    """
    result: dict[str, Any] = {}
    for key, value in data.items():
        str_value = value if isinstance(value, str) else str(value)
        rule = DES_RULE.get(key)
        if not rule:
            result[key] = value
        elif rule.get("is_encrypt") == 1:
            encrypted = des_encrypt(rule["key"].encode(), str_value.encode())
            result[rule["obfuscated_name"]] = base64.b64encode(encrypted).decode()
        else:
            result[rule["obfuscated_name"]] = value
    return result


def get_tn(data: dict[str, Any]) -> str:
    """Compute the fingerprint hash input used to derive ``tn``.

    Keys are visited in sorted order; integers are scaled by 10000, nested
    dictionaries are recursed, and empty values contribute nothing.

    Args:
        data: Fingerprint payload.

    Returns:
        Concatenated hash input string.
    """
    result = ""
    for key in sorted(data.keys()):
        value = data[key]
        if isinstance(value, int):
            result += str(value * 10000)
        elif isinstance(value, dict):
            result += get_tn(value)
        else:
            result += str(value) if value else ""
    return result


def aes_encrypt(data: bytes, key: bytes) -> str:
    """Encrypt the compressed fingerprint with AES-128-CBC.

    Args:
        data: Compressed payload bytes.
        key: 16 byte AES key.

    Returns:
        Lowercase hex ciphertext.
    """
    encoded = base64.b64encode(data)
    pad_len = 16 - (len(encoded) % 16)
    if pad_len < 16:
        encoded += b"\x00" * pad_len
    cipher = AES.new(key, AES.MODE_CBC, b"0102030405060708")
    return cipher.encrypt(pad(encoded, 16)).hex()


def get_smid(now: datetime | None = None, uid: str | None = None) -> str:
    """Build the ``smid`` fingerprint identifier.

    Args:
        now: Timestamp to use; defaults to the current local time.
        uid: UUID to hash; defaults to a random UUID.

    Returns:
        The generated smid string.
    """
    time_str = (now or datetime.now()).strftime("%Y%m%d%H%M%S")
    uid = uid or str(uuid.uuid4())
    value = f"{time_str}{hashlib.md5(uid.encode()).hexdigest()}00"
    suffix = hashlib.md5(f"smsk_web_{value}".encode()).digest()[:7].hex()
    return f"{value}{suffix}0"


def generate_signature(
    token: str,
    path: str,
    body_or_query: str,
    did: str,
    timestamp: int,
) -> tuple[str, dict[str, str]]:
    """Sign a Skland API request.

    Args:
        token: Skland token from the credential pair.
        path: Request path without query string.
        body_or_query: Raw query string for GET, or the exact JSON body for POST.
        did: Device identifier.
        timestamp: Unix timestamp used in the signature.

    Returns:
        Tuple of the signature and the header fields that must be echoed back.
    """
    header_ca = {
        "platform": "3",
        "timestamp": str(timestamp),
        "dId": did,
        "vName": "1.0.0",
    }
    raw = (
        f"{path}{body_or_query}{timestamp}"
        f"{json.dumps(header_ca, separators=(',', ':'))}"
    )
    digest = hmac.new(token.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return hashlib.md5(digest.encode()).hexdigest(), header_ca


def derive_sanity(
    raw_current: Any,
    max_ap: Any,
    recovery_ts: Any,
    seconds_per_point: int = SANITY_SECONDS_PER_POINT,
    now: float | None = None,
) -> int:
    """Extrapolate current sanity from the recovery countdown.

    The value returned by the API is a snapshot taken at the last sync, so the
    only reliable way to show live sanity is to subtract the points still
    missing from the full-recovery timestamp.

    Args:
        raw_current: Snapshot sanity value reported by the API.
        max_ap: Sanity cap.
        recovery_ts: Unix timestamp at which sanity reaches the cap.
        seconds_per_point: Recovery rate in seconds per point.
        now: Current unix timestamp; defaults to ``time.time()``.

    Returns:
        Extrapolated sanity clamped to ``[0, max_ap]``.
    """
    max_ap = int(max_ap or 0)
    raw_current = int(raw_current or 0)
    recovery_ts = int(recovery_ts or 0)
    now = time.time() if now is None else now
    if recovery_ts > now and max_ap > 0:
        missing = math.ceil((recovery_ts - now) / seconds_per_point)
        return max(0, min(max_ap - missing, max_ap))
    return max(raw_current, max_ap)


def _gzip_compress(payload: dict[str, Any]) -> bytes:
    """Serialize and gzip compress a fingerprint payload."""
    raw = json.dumps(payload, separators=(",", ":"))
    return gzip.compress(raw.encode(), compresslevel=2)


class SklandClient:
    """Async client for Skland authentication and Arknights game data."""

    def __init__(self, base_url_overrides: dict[str, str] | None = None) -> None:
        """Initialize the client.

        Args:
            base_url_overrides: Optional per-service base URLs keyed by ``"fp"``,
                ``"as"`` or ``"zonai"``. Intended for tests.
        """
        overrides = base_url_overrides or {}
        self.fp_base = overrides.get("fp", FP_BASE)
        self.as_base = overrides.get("as", AS_BASE)
        self.zonai_base = overrides.get("zonai", ZONAI_BASE)
        self._client: httpx.AsyncClient | None = None
        self._did: str | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Return the shared HTTP client, creating it on first use."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=25.0)
        return self._client

    async def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        json_data: dict[str, Any] | None = None,
        content: str | None = None,
    ) -> Any:
        """Perform one HTTP request and decode its JSON response.

        Args:
            method: HTTP method.
            url: Absolute request URL.
            headers: Request headers.
            json_data: JSON body to serialize.
            content: Raw body sent verbatim; takes precedence over json_data and
                guarantees the signed bytes equal the transmitted bytes.

        Returns:
            Decoded JSON payload.

        Raises:
            SklandError: On transport failure, non-2xx status or malformed JSON.
        """
        client = await self._get_client()
        try:
            if content is not None:
                resp = await client.request(
                    method, url, headers=headers, content=content
                )
            else:
                resp = await client.request(
                    method, url, headers=headers, json=json_data
                )
        except httpx.HTTPError as exc:
            raise SklandError(f"请求失败: {exc}") from exc

        if resp.status_code >= 400:
            # Skland explains the real reason in the body even on a 4xx.
            # raise_for_status() would discard it and leave the user staring at
            # a bare "400 Bad Request".
            detail = ""
            try:
                payload = resp.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                detail = str(payload.get("message") or payload.get("msg") or "")
            raise SklandError(detail or f"请求失败: HTTP {resp.status_code}")

        try:
            return resp.json()
        except ValueError as exc:
            raise SklandError("响应格式异常") from exc

    @staticmethod
    def _check(data: Any) -> None:
        """Raise when a business response reports a failure.

        Args:
            data: Decoded response payload.

        Raises:
            SklandError: When ``code`` is present and non-zero.
        """
        if isinstance(data, dict) and data.get("code") not in (0, None):
            raise SklandError(str(data.get("message") or "接口返回错误"))

    async def get_device_id(self) -> str:
        """Build and register a device fingerprint.

        Returns:
            The ``dId`` value required by signed requests.

        Raises:
            SklandError: When the fingerprint service rejects the payload.
        """
        if self._did:
            return self._did
        raw_uid = str(uuid.uuid4())
        aes_key = hashlib.md5(raw_uid.encode()).digest()[:8].hex()
        rsa_key = RSA.import_key(base64.b64decode(RSA_PUBLIC_KEY))
        ep = base64.b64encode(
            PKCS1_v1_5.new(rsa_key).encrypt(raw_uid.encode())
        ).decode()

        now_ms = int(time.time() * 1000)
        browser = dict(BROWSER_ENV)
        browser["vpw"] = str(uuid.uuid4())
        browser["trees"] = str(uuid.uuid4())
        browser["svm"] = now_ms
        browser["pmf"] = now_ms

        target = dict(DES_TARGET)
        target["smid"] = get_smid()
        target.update(browser)
        target["tn"] = hashlib.md5(get_tn(target).encode()).hexdigest()

        payload = {
            "appId": "default",
            "compress": 2,
            "data": aes_encrypt(
                _gzip_compress(apply_des_rules(target)), aes_key.encode()
            ),
            "encode": 5,
            "ep": ep,
            "organization": "UWXspnCCJN4sfYlNfqps",
            "os": "web",
        }
        data = await self._request(
            "POST", f"{self.fp_base}/deviceprofile/v4", json_data=payload
        )
        if not isinstance(data, dict) or data.get("code") != 1100:
            raise SklandError("设备指纹生成失败，请稍后重试")
        self._did = f"B{data['detail']['deviceId']}"
        return self._did

    def _signed_headers(
        self,
        url: str,
        method: str,
        body: str | None,
        cred: Credential,
        did: str,
    ) -> dict[str, str]:
        """Build signed request headers.

        Args:
            url: Absolute request URL; its path and query take part in the signature.
            method: HTTP method.
            body: Exact JSON body for non-GET requests.
            cred: Credential pair used to sign.
            did: Device identifier.

        Returns:
            Headers including ``cred``, ``sign`` and the echoed signature fields.
        """
        parsed = urlparse(url)
        raw = (parsed.query or "") if method.upper() == "GET" else (body or "")
        sign, header_ca = generate_signature(
            cred.token, parsed.path, raw, did, int(time.time()) - 2
        )
        headers = {
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "gzip",
            "Connection": "close",
            "X-Requested-With": "com.hypergryph.skland",
            "dId": did,
            "cred": cred.cred,
            "sign": sign,
        }
        if body is not None:
            # httpx only infers this for ``json=``; a raw body would otherwise go
            # out without it and Skland rejects that with 400. Attendance
            # sign-in is the only request that sends a raw signed body, which is
            # why it was the only endpoint returning 400.
            headers["Content-Type"] = "application/json"
        headers.update({key: str(value) for key, value in header_ca.items()})
        return headers

    async def get_authorization(self, user_token: str) -> str:
        """Exchange a Hypergryph passport token for an OAuth authorization code.

        Args:
            user_token: Hypergryph passport token.

        Returns:
            The authorization code.

        Raises:
            SklandError: When the exchange is rejected.
        """
        did = await self.get_device_id()
        data = await self._request(
            "POST",
            f"{self.as_base}/user/oauth2/v2/grant",
            headers={"User-Agent": LOGIN_USER_AGENT, "dId": did},
            json_data={"appCode": APP_CODE, "token": user_token, "type": 0},
        )
        if not isinstance(data, dict) or data.get("status") != 0:
            message = (data or {}).get("message") or (data or {}).get("msg")
            raise SklandError(str(message or "账号凭证已失效，请重新绑定"))
        return data["data"]["code"]

    async def get_credential(self, authorization: str) -> Credential:
        """Exchange an authorization code for a Skland credential pair.

        Args:
            authorization: Authorization code from :meth:`get_authorization`.

        Returns:
            The credential pair.

        Raises:
            SklandError: When the exchange is rejected.
        """
        did = await self.get_device_id()
        data = await self._request(
            "POST",
            f"{self.zonai_base}/web/v1/user/auth/generate_cred_by_code",
            headers={"User-Agent": LOGIN_USER_AGENT, "dId": did},
            json_data={"code": authorization, "kind": 1},
        )
        self._check(data)
        payload = data["data"]
        return Credential(token=payload["token"], cred=payload["cred"])

    async def get_binding_list(self, cred: Credential) -> list[UserBinding]:
        """List the Arknights roles bound to a Skland account.

        Args:
            cred: Skland credential pair.

        Returns:
            Arknights bindings; other games are filtered out.

        Raises:
            SklandError: When the request is rejected.
        """
        did = await self.get_device_id()
        url = f"{self.zonai_base}/api/v1/game/player/binding"
        data = await self._request(
            "GET", url, headers=self._signed_headers(url, "GET", None, cred, did)
        )
        self._check(data)
        bindings: list[UserBinding] = []
        for app in (data.get("data") or {}).get("list") or []:
            if app.get("appCode") != "arknights":
                continue
            for item in app.get("bindingList") or []:
                bindings.append(
                    UserBinding(
                        uid=str(item.get("uid", "")),
                        game_id=str(item.get("channelMasterId") or "1"),
                        nickname=item.get("nickName", ""),
                        channel_name=item.get("channelName", ""),
                    )
                )
        return bindings

    async def get_player_info(self, cred: Credential, uid: str) -> dict[str, Any]:
        """Fetch the full in-game data snapshot for a role.

        Args:
            cred: Skland credential pair.
            uid: Role uid.

        Returns:
            The ``data`` payload, containing ``status``, ``chars``,
            ``charInfoMap``, ``building`` and related sections.

        Raises:
            SklandError: When the request is rejected.
        """
        did = await self.get_device_id()
        url = f"{self.zonai_base}/api/v1/game/player/info?uid={uid}"
        data = await self._request(
            "GET", url, headers=self._signed_headers(url, "GET", None, cred, did)
        )
        self._check(data)
        return data.get("data") or {}

    async def sign_arknights(
        self, cred: Credential, binding: UserBinding
    ) -> SignInResult:
        """Perform the daily Skland attendance sign-in for a role.

        A rejection is returned rather than raised, because "already signed in"
        is a normal business outcome.

        Args:
            cred: Skland credential pair.
            binding: Role to sign in.

        Returns:
            The sign-in outcome.

        Raises:
            SklandError: On transport or decoding failure.
        """
        did = await self.get_device_id()
        url = f"{self.zonai_base}/api/v1/game/attendance"
        body = json.dumps(
            {"gameId": binding.game_id, "uid": binding.uid}, separators=(",", ":")
        )
        headers = self._signed_headers(url, "POST", body, cred, did)
        data = await self._request("POST", url, headers=headers, content=body)
        if not isinstance(data, dict) or data.get("code") != 0:
            return SignInResult(
                success=False,
                nickname=binding.nickname,
                error=str((data or {}).get("message") or "签到失败"),
            )
        awards = [
            f"{(award.get('resource') or {}).get('name', '未知')}x{award.get('count', 1)}"
            for award in (data.get("data") or {}).get("awards") or []
        ]
        return SignInResult(success=True, nickname=binding.nickname, awards=awards)

    @staticmethod
    def parse_sanity(data: dict[str, Any], now: float | None = None) -> dict[str, int]:
        """Extract live sanity values from a player info payload.

        Args:
            data: The ``data`` section of a player info response.
            now: Current unix timestamp; defaults to ``time.time()``.

        Returns:
            Mapping with ``current``, ``max`` and ``complete_recovery_time``.
        """
        ap = ((data or {}).get("status") or {}).get("ap") or {}
        max_ap = int(ap.get("max") or 0)
        recovery = int(ap.get("completeRecoveryTime") or 0)
        return {
            "current": derive_sanity(
                ap.get("current"),
                max_ap,
                recovery,
                SANITY_SECONDS_PER_POINT,
                now,
            ),
            "max": max_ap,
            "complete_recovery_time": recovery,
        }

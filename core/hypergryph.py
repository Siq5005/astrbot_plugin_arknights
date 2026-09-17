"""Hypergryph passport login.

The only supported login flow is scanning a QR code with the Skland app, which
yields the Hypergryph passport token that the Skland client then exchanges for
game credentials.

This module never imports ``astrbot``.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

AS_BASE = "https://as.hypergryph.com"

# Skland app code. Verified to be accepted by gen_scan/login and to be the same
# app code used later by the oauth2 grant exchange.
SKLAND_APP_CODE = "4ca99fa6b56cc2ba"

# scan_status only carries a scanCode when it reports this status. Every other
# value means the login has not finished: 100 is "未扫码" and a scanned-but-
# unconfirmed code reports its own status too. They must all keep the caller
# polling — treating the intermediate state as an error aborted the login the
# instant the user scanned, before they could confirm in the app.
SCAN_STATUS_SUCCESS = 0


class HypergryphError(Exception):
    """Raised when a Hypergryph passport request fails."""


class HypergryphClient:
    """Client for Hypergryph passport login endpoints."""

    def __init__(self, base_url: str = AS_BASE) -> None:
        """Initialize the client.

        Args:
            base_url: Hypergryph passport service base URL.
        """
        self.base_url = base_url
        self._client: httpx.AsyncClient | None = None

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
        path: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call a passport endpoint and return its JSON payload.

        Args:
            method: HTTP method.
            path: Path appended to the base URL.
            params: Query parameters.
            json_data: JSON request body.

        Returns:
            Decoded JSON payload.

        Raises:
            HypergryphError: On transport failure, non-2xx status, malformed JSON
                or a non-zero ``status`` field.
        """
        client = await self._get_client()
        try:
            resp = await client.request(
                method,
                f"{self.base_url}{path}",
                params=params,
                json=json_data,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            raise HypergryphError(f"请求失败: {exc}") from exc
        except ValueError as exc:
            raise HypergryphError("响应格式异常") from exc
        if not isinstance(data, dict):
            raise HypergryphError("响应格式异常")
        if data.get("status") != 0:
            raise HypergryphError(
                str(data.get("msg") or data.get("message") or "操作失败")
            )
        return data

    async def create_qr(self) -> dict[str, str]:
        """Request a login QR code.

        Returns:
            Mapping with ``scan_id`` and ``scan_url``. ``scan_url`` uses the
            ``hypergryph://`` custom scheme, so callers must render it as a QR
            image rather than sending it as a link.

        Raises:
            HypergryphError: When the request is rejected.
        """
        data = await self._request(
            "POST",
            "/general/v1/gen_scan/login",
            json_data={"appCode": SKLAND_APP_CODE},
        )
        payload = data.get("data") or {}
        return {
            "scan_id": str(payload.get("scanId", "")),
            "scan_url": str(payload.get("scanUrl", "")),
        }

    async def poll_qr(self, scan_id: str) -> str | None:
        """Poll the state of a login QR code.

        Args:
            scan_id: Identifier returned by :meth:`create_qr`.

        Returns:
            The ``scanCode`` once the user has scanned and confirmed, otherwise
            ``None`` while the login is still in progress.

        Raises:
            HypergryphError: When the request itself fails.
        """
        client = await self._get_client()
        try:
            resp = await client.get(
                f"{self.base_url}/general/v1/scan_status",
                params={"scanId": scan_id},
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            raise HypergryphError(f"请求失败: {exc}") from exc
        except ValueError as exc:
            raise HypergryphError("响应格式异常") from exc
        if not isinstance(data, dict):
            raise HypergryphError("响应格式异常")
        if data.get("status") != SCAN_STATUS_SUCCESS:
            return None
        return str((data.get("data") or {}).get("scanCode") or "") or None

    async def get_token_by_scan_code(self, scan_code: str) -> str:
        """Exchange a scanned code for a passport token.

        Args:
            scan_code: Code returned by :meth:`poll_qr`.

        Returns:
            The Hypergryph passport token.

        Raises:
            HypergryphError: When the exchange is rejected.
        """
        data = await self._request(
            "POST",
            "/user/auth/v1/token_by_scan_code",
            json_data={"scanCode": scan_code},
        )
        return str((data.get("data") or {}).get("token", ""))

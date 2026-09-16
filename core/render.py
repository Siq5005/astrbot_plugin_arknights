"""HTML to image rendering built on Playwright and Jinja2.

Templates reference local assets with an ``__ASSET__/`` prefix, which is
resolved to a data URI before rendering so no ``file://`` resolution is needed
inside the browser. A single Chromium instance is reused across renders.

This is an independent implementation; it intentionally does not derive from the
AGPL-licensed renderers in other plugins.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import mimetypes
import re
import time
import uuid
from pathlib import Path
from typing import Any

import jinja2

logger = logging.getLogger(__name__)

ASSET_PATTERN = re.compile(r"__ASSET__/([A-Za-z0-9_./-]+)")
CACHE_MAX_AGE_SECONDS = 300


class Renderer:
    """Render Jinja2 templates to JPEG cards."""

    def __init__(
        self,
        templates_dir: Path,
        cache_dir: Path,
        timeout_ms: int = 30000,
    ) -> None:
        """Initialize the renderer.

        Args:
            templates_dir: Directory containing the HTML templates and assets.
            cache_dir: Directory that receives the rendered images.
            timeout_ms: Per render timeout in milliseconds.
        """
        self.templates_dir = Path(templates_dir)
        self.cache_dir = Path(cache_dir)
        self.timeout_ms = timeout_ms
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(self.templates_dir)),
            autoescape=True,
        )
        self._lock = asyncio.Lock()
        self._playwright: Any = None
        self._browser: Any = None

    async def start(self) -> bool:
        """Launch the shared browser instance.

        Returns:
            ``True`` when a browser is available, ``False`` otherwise.
        """
        async with self._lock:
            if self._browser is not None:
                return True
            try:
                from playwright.async_api import async_playwright
            except ImportError:
                logger.error("未安装 playwright，图片渲染不可用")
                return False
            try:
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch()
                return True
            except Exception as exc:  # noqa: BLE001 - degrade to text output
                logger.error(
                    "启动 Chromium 失败（是否已执行 playwright install chromium?）: %s",
                    exc,
                )
                await self._stop_locked()
                return False

    async def close(self) -> None:
        """Shut the browser down and release Playwright."""
        async with self._lock:
            await self._stop_locked()

    async def _stop_locked(self) -> None:
        """Tear down browser and playwright; caller must hold the lock."""
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception as exc:  # noqa: BLE001 - shutdown must not raise
                logger.debug("关闭浏览器失败: %s", exc)
            self._browser = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception as exc:  # noqa: BLE001 - shutdown must not raise
                logger.debug("停止 playwright 失败: %s", exc)
            self._playwright = None

    def _prune_cache(self) -> None:
        """Delete rendered images older than the cache window."""
        cutoff = time.time() - CACHE_MAX_AGE_SECONDS
        try:
            for path in self.cache_dir.glob("render_*.jpg"):
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
        except OSError as exc:
            logger.debug("清理渲染缓存失败: %s", exc)

    def _inline_assets(self, html: str) -> str:
        """Replace ``__ASSET__/`` references with base64 data URIs.

        Args:
            html: Rendered template HTML.

        Returns:
            HTML with local asset references inlined.
        """
        root = self.templates_dir.resolve()

        def replace(match: re.Match[str]) -> str:
            candidate = (root / match.group(1)).resolve()
            if root not in candidate.parents or not candidate.is_file():
                return match.group(0)
            try:
                mime = (
                    mimetypes.guess_type(candidate.name)[0]
                    or "application/octet-stream"
                )
                encoded = base64.b64encode(candidate.read_bytes()).decode()
            except OSError as exc:
                logger.debug("内联资源失败 (%s): %s", candidate, exc)
                return match.group(0)
            return f"data:{mime};base64,{encoded}"

        return ASSET_PATTERN.sub(replace, html)

    async def render_html(
        self, template_name: str, data: dict[str, Any]
    ) -> Path | None:
        """Render a template to a JPEG file.

        Args:
            template_name: Template filename relative to ``templates_dir``.
            data: Variables passed to the template.

        Returns:
            Path of the rendered image, or ``None`` when rendering failed. The
            caller is expected to fall back to a text reply.
        """
        try:
            html = self._inline_assets(
                self._env.get_template(template_name).render(**data)
            )
        except Exception as exc:  # noqa: BLE001 - template errors degrade to text
            logger.error("渲染模板 %s 失败: %s", template_name, exc)
            return None

        if not await self.start():
            return None

        self._prune_cache()
        output = self.cache_dir / f"render_{uuid.uuid4().hex[:8]}.jpg"
        page = None
        context = None
        try:
            context = await self._browser.new_context(
                device_scale_factor=2, viewport={"width": 1000, "height": 800}
            )
            page = await context.new_page()
            await page.set_content(html, wait_until="load", timeout=self.timeout_ms)
            # Wait for remote avatars so the measured bounding box is final.
            await page.evaluate(
                "() => Promise.all(Array.from(document.images).map("
                "img => img.complete ? null : new Promise(resolve => {"
                " img.onload = resolve; img.onerror = resolve; })))"
            )
            box = await page.locator("body > *").first.bounding_box()
            if box:
                await page.set_viewport_size(
                    {"width": int(box["width"]) + 2, "height": int(box["height"]) + 2}
                )
                await page.screenshot(
                    path=str(output), clip=box, type="jpeg", quality=85
                )
            else:
                await page.screenshot(
                    path=str(output), full_page=True, type="jpeg", quality=85
                )
            return output
        except Exception as exc:  # noqa: BLE001 - degrade to text output
            logger.error("渲染 %s 截图失败: %s", template_name, exc)
            return None
        finally:
            if page is not None:
                try:
                    await page.close()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("关闭页面失败: %s", exc)
            if context is not None:
                try:
                    await context.close()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("关闭上下文失败: %s", exc)

# 森空岛自建公告源 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让插件默认从一个自建聚合源（森空岛「官方」栏目，含 PV/EP 视频）推送明日方舟官方动态，并在该源连续失败时自动告警并降级到官网公告源。

**Architecture:** 分两个子系统。**服务端**（部署在 HK 的 `youyou.ink`）持有一份森空岛凭证，后台轮询「官方」栏目并缓存，通过 `X-API-Key` 鉴权的 HTTP 接口对外提供归一化数据——插件使用者因此不需要任何鹰角账号。**插件端**新增一个源客户端，把服务端返回归一化成与现有官网源完全相同的记录结构，复用现有推送与渲染路径；源选择、失败滑动窗口与降级状态机都在插件端，默认自建源、失败降级官网源。

**Tech Stack:** Python 3.11；服务端 FastAPI + uvicorn + httpx + pycryptodome（部署在 HK 的 Debian 12 + Caddy 反代 + systemd）；插件端沿用 AstrBot 插件 API、httpx、Playwright 渲染。

**Spec:** 本文件即规格。设计结论来自以下已核实的事实：

- 森空岛内容接口在 `zonai.skland.com`，与插件 `core/skland.py` 已在用的主机相同；鉴权是 `dId` + `sign` + `cred`，**插件已实现全部密码学部分**，无需新增逆向。
- 明日方舟官方栏目：`gameId=1`、`cateId=1`（`kind=100`）。
- 列表接口：`GET /web/v2/home/index?gameId=1&cateId=1&pageSize=10&sortType=2`（`sortType=2` = 最新）。
- **`pageSize` 上限为 10**，传 11 即报 `参数错误`；翻页用响应里的 `pageToken` + `hasMore`。
- 匿名（仅 `dId`，或空凭证签名）会被拒，**必须登录**。
- 详情接口 `GET /web/v2/item?id=<id>`；原文链接 `https://www.skland.com/article?id=<id>`（实测 200）。
- 视频字段在详情 `videoList[].infos[]`，只有 m3u8（1080P/720P/480P）；列表项自带 `imageList`/`thumbnail` 封面。**本方案不下载视频**，只推封面 + 标题 + 正文摘要。
- `tags` 是**实体标签**（游戏/品牌/活动/干员），不是内容类型标签——过滤只能靠 `viewKind`、`cateId` 和标题关键词。
- `viewKind`：`1` 视频、`2` 图集、`3` 文章。
- 实测 47 天 140 条官方内容：视频 10 条（7%）。
- **推送内容口径（已定）**：只保留官方栏目，并按标题关键词排除社区/工具向内容——`签到福利`、`周记表`、`每日谜题`、`猜猜我是谁`、`创作集锦`、`版区作品`、`模组`、`游戏工具`、`有奖活动`、`创作者应援`、`讨论楼`、`热议`。实测排除后剩 109/140 条，约 2.3 条/天、16.2 条/周。关键词可在插件配置中改。
- 官网源 `LATEST` 只有 12 条、跨 5 周；森空岛官方覆盖其中 10/12（83%），另有 130/140（93%）是官网没有的。
- HK（162.211.183.29，Debian 12，1C/960M）到 `zonai.skland.com`(0.4s)、`bbs.hycdn.cn`(0.29s)、`ak.hypergryph.com`(0.66s) 全部连通；已运行 Caddy v2.11.4 并占用 80/443。

## Global Constraints

- **版本一致性**：任何版本变更必须同时改 4 处——`metadata.yaml` 的 `version`、`main.py` 的 `PLUGIN_VERSION`、`README.md` 的版本徽章、`README.md` 更新日志标题。`tests/integration_check.py` 会断言这四处一致。
- **日志**：插件代码只能 `from astrbot.api import logger`；禁止 `logging.getLogger`（AstrBot 市场规则）。服务端代码与框架无关，用标准库 `logging`。
- **注释与文档字符串**：沿用仓库现状——**英文**注释，Google 风格 docstring（`Args:` / `Returns:` / `Raises:`）。
- **格式**：提交前 `ruff format .` 与 `ruff check .` 必须干净。
- **测试命令**：
  - 插件单测：`/Users/coe/project/AstrBot/.venv/bin/python -m pytest tests -q`
  - 集成检查：`/Users/coe/project/AstrBot/.venv/bin/python tests/integration_check.py`
  - 服务端单测：`/opt/arksource/venv/bin/python -m pytest server/tests -q`（本地开发用同一命令，路径换成仓库内 venv）
- **依赖**：服务端只允许 `fastapi`、`uvicorn[standard]`、`httpx`、`pycryptodome`、`qrcode`。不得引入 ORM、数据库或任务队列——缓存用内存字典 + 一个 JSON 文件。
- **不复制 AGPL 代码**：`astrbot_plugin_endfield`、`astrbot_plugin_mrfz_haunting_query` 是 AGPL-3.0，本仓库保持 MIT，只做独立实现。
- **服务端不得写死环境相关的绝对路径**：全部走环境变量（见 Task 1 的 `Settings`）。

---

## 文件结构

**服务端**（新增，随插件仓库一起分发，便于自建）

| 文件 | 职责 |
|:--|:--|
| `server/requirements.txt` | 依赖钉版本 |
| `server/app/__init__.py` | 包标记 |
| `server/app/settings.py` | 环境变量 → `Settings` 数据类 |
| `server/app/skland_client.py` | **从 `core/skland.py` 原样复制**的森空岛协议客户端（设备指纹 + 签名 + cred） |
| `server/app/hypergryph_client.py` | **从 `core/hypergryph.py` 原样复制**的扫码登录客户端 |
| `server/app/credentials.py` | 凭证文件读写（`0600`），`user_token` 的长期保存 |
| `server/app/feed.py` | 拉取「官方」栏目并归一化 |
| `server/app/cache.py` | 后台轮询任务 + 内存缓存 |
| `server/app/main.py` | FastAPI 应用、`X-API-Key` 鉴权、两个端点 |
| `server/scripts/login.py` | 一次性扫码登录，签发长期 `user_token` |
| `server/deploy/arksource.service` | systemd unit |
| `server/deploy/caddy-snippet.txt` | 需要并入 HK `Caddyfile` 的片段 |
| `server/tests/*.py` | 服务端单测（httpx `MockTransport`，不联网） |
| `server/README.md` | 自建部署说明 |

**插件端**（修改）

| 文件 | 职责 |
|:--|:--|
| `core/feed.py` | 新增：自建源客户端，归一化成与官网源同一形态 |
| `core/store.py` | 修改：持久化当前生效源与失败时间戳 |
| `main.py` | 修改：源选择、失败窗口、降级与告警、排除过滤 |
| `_conf_schema.json` | 修改：新增 6 个配置项 |
| `tests/test_feed.py` | 新增：`core/feed.py` 单测 |
| `tests/integration_check.py` | 修改：降级/过滤/源选择的断言 |
| `README.md` / `metadata.yaml` | 修改：版本 0.3.9 → 0.4.0、配置说明、更新日志 |

---

# Phase A：聚合服务

## Task 1: 服务骨架与森空岛客户端落地

**Files:**
- Create: `server/requirements.txt`
- Create: `server/app/__init__.py`
- Create: `server/app/settings.py`
- Create: `server/app/skland_client.py`（`cp core/skland.py`）
- Create: `server/app/hypergryph_client.py`（`cp core/hypergryph.py`）
- Test: `server/tests/test_settings.py`

**Interfaces:**
- Consumes: 无（第一个任务）
- Produces: `Settings` 数据类，字段 `api_key: str`、`user_token: str`、`credential_file: Path`、`state_file: Path`、`poll_interval_seconds: int`、`window_hours: int`、`host: str`、`port: int`、`stale_minutes: int`；类方法 `Settings.from_env() -> Settings`。`skland_client.SklandClient` 与 `hypergryph_client.HypergryphClient` 保持与插件内同名类完全一致的公开方法。

- [ ] **Step 1: 写失败的测试**

```python
# server/tests/test_settings.py
"""Settings are read from the environment so the same code runs locally and on HK."""

import os
from pathlib import Path

from app.settings import Settings


def test_from_env_applies_defaults(monkeypatch):
    for key in list(os.environ):
        if key.startswith("ARKSOURCE_"):
            monkeypatch.delenv(key, raising=False)

    settings = Settings.from_env()

    assert settings.host == "127.0.0.1"
    assert settings.port == 8788
    assert settings.poll_interval_seconds == 600
    assert settings.window_hours == 72
    assert settings.stale_minutes == 60
    assert settings.api_key == ""


def test_from_env_reads_overrides(monkeypatch):
    monkeypatch.setenv("ARKSOURCE_API_KEY", "secret-key")
    monkeypatch.setenv("ARKSOURCE_PORT", "9999")
    monkeypatch.setenv("ARKSOURCE_CREDENTIAL_FILE", "/tmp/cred.json")

    settings = Settings.from_env()

    assert settings.api_key == "secret-key"
    assert settings.port == 9999
    assert settings.credential_file == Path("/tmp/cred.json")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `/Users/coe/project/AstrBot/.venv/bin/python -m pytest server/tests/test_settings.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: 写最小实现**

```text
# server/requirements.txt
fastapi==0.115.6
uvicorn[standard]==0.34.0
httpx==0.28.1
pycryptodome==3.21.0
qrcode==8.0
pytest==8.3.4
```

```python
# server/app/__init__.py
"""Self-hosted Skland announcement aggregator for astrbot_plugin_arknights."""
```

```python
# server/app/settings.py
"""Runtime configuration, read from ``ARKSOURCE_*`` environment variables.

Keeping every deployment-specific value here means the same code runs in a local
venv and on the public host without edits.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    """Read an integer environment variable.

    Args:
        name: Variable name.
        default: Value used when unset or unparsable.

    Returns:
        The parsed integer, or ``default``.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class Settings:
    """Aggregator settings."""

    api_key: str
    credential_file: Path
    state_file: Path
    host: str
    port: int
    poll_interval_seconds: int
    window_hours: int
    stale_minutes: int

    @classmethod
    def from_env(cls) -> "Settings":
        """Build settings from the environment.

        Returns:
            A populated :class:`Settings`.
        """
        return cls(
            api_key=os.environ.get("ARKSOURCE_API_KEY", "").strip(),
            credential_file=Path(
                os.environ.get("ARKSOURCE_CREDENTIAL_FILE", "/opt/arksource/credentials.json")
            ),
            state_file=Path(
                os.environ.get("ARKSOURCE_STATE_FILE", "/opt/arksource/state.json")
            ),
            host=os.environ.get("ARKSOURCE_HOST", "127.0.0.1").strip(),
            port=_env_int("ARKSOURCE_PORT", 8788),
            poll_interval_seconds=_env_int("ARKSOURCE_POLL_INTERVAL", 600),
            window_hours=_env_int("ARKSOURCE_WINDOW_HOURS", 72),
            stale_minutes=_env_int("ARKSOURCE_STALE_MINUTES", 60),
        )
```

- [ ] **Step 4: 复制两个客户端并加来源说明**

```bash
cp core/skland.py server/app/skland_client.py
cp core/hypergryph.py server/app/hypergryph_client.py
```

在 `server/app/skland_client.py` 文件顶部 docstring 之后插入如下注释（不要改动任何逻辑——这两个文件是**原样副本**，与插件共用一份协议实现）：

```python
# VENDORED from astrbot_plugin_arknights/core/skland.py.
# Kept byte-compatible with the plugin copy on purpose: the same device
# fingerprint and request-signing code must stay in lockstep, and trimming it
# here would let the two drift. Re-copy with `cp` after changing the original.
```

同样在 `server/app/hypergryph_client.py` 顶部插入：

```python
# VENDORED from astrbot_plugin_arknights/core/hypergryph.py.
# Re-copy with `cp` after changing the original.
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd server && /Users/coe/project/AstrBot/.venv/bin/python -m pytest tests/test_settings.py -q`
Expected: PASS（2 passed）

- [ ] **Step 6: 验证 vendored 客户端可导入且无框架依赖**

Run: `cd server && /Users/coe/project/AstrBot/.venv/bin/python -c "from app.skland_client import SklandClient; from app.hypergryph_client import HypergryphClient; print('ok')"`
Expected: 输出 `ok`（若报 `ModuleNotFoundError: astrbot`，说明复制源文件被改过，必须还原为原样副本）

- [ ] **Step 7: 提交**

```bash
git add server/requirements.txt server/app/__init__.py server/app/settings.py \
        server/app/skland_client.py server/app/hypergryph_client.py server/tests/test_settings.py
git commit -m "feat(server): scaffold aggregator settings and vendor skland clients"
```

---

## Task 2: 「官方」栏目抓取与归一化

**Files:**
- Create: `server/app/feed.py`
- Test: `server/tests/test_feed.py`

**Interfaces:**
- Consumes: `app.skland_client.SklandClient`（`get_device_id()` / `get_authorization()` / `get_credential()` / `_signed_headers()` / `_request()`）。**注意**：`_signed_headers` 与 `_request` 是下划线开头的内部方法，Task 1 的副本必须保留它们的现有签名：`_signed_headers(url, method, body, cred, did) -> dict[str, str]` 与 `_request(method, url, headers=None, json_data=None, content=None) -> Any`。
- Produces:
  - `ZONAI_BASE`、`FEED_PATH`、`ARTICLE_URL_TEMPLATE`、`OFFICIAL_GAME_ID = 1`、`OFFICIAL_CATE_ID = 1`、`PAGE_SIZE = 10`
  - `class FeedError(Exception)`
  - `async def fetch_official(client, user_token: str, window_hours: int = 72, now: int | None = None) -> list[dict[str, Any]]` —— 返回**最新在前**的归一化条目，元素字段固定为：`id: str`、`title: str`、`kind: int`、`published_at: int`、`cover: str`、`images: list[str]`、`text: str`、`url: str`、`tags: list[str]`
  - `def normalize(item: dict[str, Any], detail_item: dict[str, Any] | None = None, tags: list[dict[str, Any]] | None = None) -> dict[str, Any]`
  - `def document_to_text(document: dict[str, Any]) -> str`

- [ ] **Step 1: 写失败的测试**

```python
# server/tests/test_feed.py
"""Feed normalisation is pure, so it is tested without touching the network."""

from app.feed import document_to_text, normalize


def test_document_to_text_joins_text_blocks_in_order():
    document = {
        "blockIds": ["a", "b", "c"],
        "blockMap": {
            "b": {
                "kind": "text",
                "text": {"inlineElements": [{"kind": "text", "text": {"text": "第二行"}}]},
            },
            "a": {
                "kind": "text",
                "text": {"inlineElements": [{"kind": "text", "text": {"text": "第一行"}}]},
            },
            "c": {"kind": "image", "image": {"id": "x"}},
        },
    }

    assert document_to_text(document) == "第一行\n第二行"


def test_document_to_text_tolerates_missing_fields():
    assert document_to_text({}) == ""
    assert document_to_text({"blockIds": ["a"], "blockMap": {}}) == ""


def test_normalize_maps_list_item_to_stable_shape():
    item = {
        "id": "6377378",
        "title": "《明日方舟》「书行山海」特别公益PV",
        "viewKind": 1,
        "publishedAtTs": "1791709243",
        "thumbnail": "https://bbs.hycdn.cn/cover.webp",
        "imageList": [
            {"url": "https://bbs.hycdn.cn/a.webp", "infos": [{"url": "https://bbs.hycdn.cn/a-inner.webp"}]}
        ],
        "tagIds": [474],
    }
    tags = [{"id": 474, "name": "明日方舟"}, {"id": 505, "name": "泰拉记事社"}]

    record = normalize(item, tags=tags)

    assert record["id"] == "6377378"
    assert record["kind"] == 1
    assert record["published_at"] == 1791709243
    assert record["cover"] == "https://bbs.hycdn.cn/cover.webp"
    assert record["images"] == ["https://bbs.hycdn.cn/a.webp"]
    assert record["tags"] == ["明日方舟", "泰拉记事社"]
    assert record["url"] == "https://www.skland.com/article?id=6377378"
    assert record["text"] == ""


def test_normalize_uses_thumbnail_when_image_list_is_empty():
    item = {"id": "1", "title": "t", "viewKind": 3, "publishedAtTs": 10, "thumbnail": "https://x/y.webp"}

    record = normalize(item)

    assert record["cover"] == "https://x/y.webp"
    assert record["images"] == []


def test_normalize_falls_back_to_first_image_for_cover():
    item = {"id": "1", "title": "t", "viewKind": 3, "publishedAtTs": 10,
            "imageList": [{"url": "https://bbs.hycdn.cn/a.webp"}]}

    record = normalize(item)

    assert record["cover"] == "https://bbs.hycdn.cn/a.webp"


def test_normalize_reads_text_from_document():
    item = {"id": "1", "title": "t", "viewKind": 1, "publishedAtTs": 10}
    detail = {
        "document": {
            "blockIds": ["a"],
            "blockMap": {
                "a": {"kind": "text", "text": {"inlineElements": [{"kind": "text", "text": {"text": "正文"}}]}}
            },
        }
    }

    assert normalize(item, detail_item=detail)["text"] == "正文"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd server && /Users/coe/project/AstrBot/.venv/bin/python -m pytest tests/test_feed.py -q`
Expected: FAIL — `ImportError: cannot import name 'document_to_text' from 'app.feed'`

- [ ] **Step 3: 写实现**

```python
# server/app/feed.py
"""Read the Arknights "official" column from Skland and normalise it.

Skland exposes the community content API on the same host the plugin already
signs against. The official column is ``gameId=1`` (Arknights) plus
``cateId=1`` (the platform's own "官方" category, whose ``kind`` is 100/Admin),
sorted newest first with ``sortType=2``.

Two hard limits shape this module: ``pageSize`` may not exceed 10 (anything
larger is rejected as 参数错误), and paging is token based via ``pageToken``
alongside a ``hasMore`` flag.
"""

from __future__ import annotations

import asyncio
from typing import Any

ZONAI_BASE = "https://zonai.skland.com"
OFFICIAL_GAME_ID = 1
OFFICIAL_CATE_ID = 1
PAGE_SIZE = 10
FEED_PATH = (
    "/web/v2/home/index?gameId={game}&cateId={cate}&pageSize={size}&sortType=2"
)
ARTICLE_URL_TEMPLATE = "https://www.skland.com/article?id={id}"

# Politeness delay between pages; the endpoint validates parameters strictly and
# a burst of ten requests is unnecessary.
_PAGE_DELAY_SECONDS = 0.5
# Hard stop so a feed that never reports hasMore=false cannot loop forever.
_MAX_PAGES = 40


class FeedError(Exception):
    """Raised when the official feed cannot be read."""


def document_to_text(document: dict[str, Any]) -> str:
    """Flatten a Skland rich-text document into plain text.

    Blocks are ordered by ``blockIds``; only text blocks contribute.

    Args:
        document: The ``document`` object of a Skland content item.

    Returns:
        Newline-joined block text, empty when there is none.
    """
    if not isinstance(document, dict):
        return ""
    block_map = document.get("blockMap")
    block_ids = document.get("blockIds")
    if not isinstance(block_map, dict) or not isinstance(block_ids, list):
        return ""

    lines: list[str] = []
    for block_id in block_ids:
        block = block_map.get(block_id)
        if not isinstance(block, dict) or block.get("kind") != "text":
            continue
        text_prop = block.get("text")
        if not isinstance(text_prop, dict):
            continue
        elements = text_prop.get("inlineElements")
        if not isinstance(elements, list):
            continue
        parts: list[str] = []
        for element in elements:
            if not isinstance(element, dict):
                continue
            inner = element.get("text")
            if isinstance(inner, dict) and inner.get("text"):
                parts.append(str(inner["text"]))
        line = "".join(parts)
        if line:
            lines.append(line)
    return "\n".join(lines)


def _image_urls(item: dict[str, Any]) -> list[str]:
    """Collect the image URLs of an item.

    Args:
        item: Raw Skland content item.

    Returns:
        Deduplicated image URLs in feed order.
    """
    urls: list[str] = []
    for entry in item.get("imageList") or []:
        if not isinstance(entry, dict):
            continue
        url = str(entry.get("url") or "")
        if url and url not in urls:
            urls.append(url)
    return urls


def normalize(
    item: dict[str, Any],
    detail_item: dict[str, Any] | None = None,
    tags: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Reduce a raw Skland item to the aggregator's stable wire shape.

    Args:
        item: Raw item, either from the feed list or the detail endpoint.
        detail_item: Detail payload when available; supplies the body text.
        tags: Tag objects from the feed row.

    Returns:
        A dict with ``id``, ``title``, ``kind``, ``published_at``, ``cover``,
        ``images``, ``text``, ``url`` and ``tags``.
    """
    source = detail_item or item
    item_id = str(source.get("id") or item.get("id") or "")
    images = _image_urls(source) or _image_urls(item)
    cover = str(source.get("thumbnail") or item.get("thumbnail") or "")
    if not cover and images:
        cover = images[0]
    if not cover:
        # The video cover lives on videoList when the item has no thumbnail.
        for video in source.get("videoList") or []:
            if isinstance(video, dict):
                inner = video.get("cover")
                if isinstance(inner, dict) and inner.get("url"):
                    cover = str(inner["url"])
                    break

    text = document_to_text(source.get("document") or {})
    if not text:
        texts = source.get("texts")
        if isinstance(texts, list):
            text = "\n".join(
                str(entry.get("content") or "")
                for entry in texts
                if isinstance(entry, dict) and entry.get("content")
            )

    tag_names = [
        str(tag.get("name"))
        for tag in (tags or [])
        if isinstance(tag, dict) and tag.get("name")
    ]

    try:
        published_at = int(source.get("publishedAtTs") or item.get("publishedAtTs") or 0)
    except (TypeError, ValueError):
        published_at = 0

    return {
        "id": item_id,
        "title": str(source.get("title") or item.get("title") or ""),
        "kind": int(source.get("viewKind") or item.get("viewKind") or 0),
        "published_at": published_at,
        "cover": cover,
        "images": images,
        "text": text,
        "url": ARTICLE_URL_TEMPLATE.format(id=item_id),
        "tags": tag_names,
    }


async def fetch_official(
    client: Any,
    window_hours: int = 72,
    now: int | None = None,
) -> list[dict[str, Any]]:
    """Read the Arknights official column, newest first.

    Args:
        client: A signed ``SklandClient`` instance.
        window_hours: Stop paging once items fall outside this age window.
        now: Unix seconds to compare against; defaults to the system clock.

    Returns:
        Normalised records, newest first.

    Raises:
        FeedError: When the feed cannot be read or paged.
    """
    import time

    did = await client.get_device_id()
    authorization = await client.get_authorization(
        getattr(client, "user_token", "") or client.settings_user_token
    )
    cred = await client.get_credential(authorization)

    reference = int(now if now is not None else time.time())
    cutoff = reference - max(1, window_hours) * 3600

    records: list[dict[str, Any]] = []
    page_token: str | None = None
    seen: set[str] = set()

    for page in range(_MAX_PAGES):
        path = FEED_PATH.format(
            game=OFFICIAL_GAME_ID, cate=OFFICIAL_CATE_ID, size=PAGE_SIZE
        )
        if page_token:
            path = f"{path}&pageToken={page_token}"
        url = ZONAI_BASE + path
        headers = client._signed_headers(url, "GET", None, cred, did)
        try:
            payload = await client._request("GET", url, headers=headers)
        except Exception as exc:  # noqa: BLE001 - surfaced as FeedError
            raise FeedError(f"森空岛接口请求失败: {exc}") from exc

        if not isinstance(payload, dict) or payload.get("code") not in (0, None):
            message = ""
            if isinstance(payload, dict):
                message = str(payload.get("message") or "")
            raise FeedError(f"森空岛接口返回异常: {message or payload}")

        data = payload.get("data") or {}
        rows = data.get("list") or []
        if not rows:
            break

        oldest = reference
        for row in rows:
            raw = row.get("item") if isinstance(row, dict) else None
            if not isinstance(raw, dict):
                continue
            item_id = str(raw.get("id") or "")
            if not item_id or item_id in seen:
                continue
            seen.add(item_id)
            record = normalize(raw, tags=row.get("tags") or [])
            oldest = min(oldest, record["published_at"] or reference)
            if record["published_at"] and record["published_at"] < cutoff:
                continue
            records.append(record)

        page_token = data.get("pageToken")
        if not data.get("hasMore") or not page_token or oldest < cutoff:
            break
        if page < _MAX_PAGES - 1:
            await asyncio.sleep(_PAGE_DELAY_SECONDS)

    records.sort(key=lambda entry: (entry["published_at"], entry["id"]), reverse=True)
    return records
```

**注意**：`fetch_official` 需要 `user_token`。Task 1 的 `SklandClient` 副本没有 `user_token` 属性，也没有 `settings_user_token`。为避免改动 vendored 副本，**把签名改为显式传入**——把上面 `authorization = ...` 两行替换为：

```python
    authorization = await client.get_authorization(user_token)
```

并把函数签名改为：

```python
async def fetch_official(
    client: Any,
    user_token: str,
    window_hours: int = 72,
    now: int | None = None,
) -> list[dict[str, Any]]:
```

同时更新 docstring 的 `Args:` 增加 `user_token: Long-lived Hypergryph passport token.`

- [ ] **Step 4: 运行测试确认通过**

Run: `cd server && /Users/coe/project/AstrBot/.venv/bin/python -m pytest tests/test_feed.py -q`
Expected: PASS（6 passed）

- [ ] **Step 5: 补一个分页测试，锁住「pageSize 不得超过 10」**

```python
# 追加到 server/tests/test_feed.py
import httpx
import pytest

from app.feed import FeedError, fetch_official


class _FakeSkland:
    """Minimal stand-in for SklandClient, recording requested URLs."""

    def __init__(self, pages, user_token="tok"):
        self._pages = pages
        self.urls = []
        self.user_token = user_token

    async def get_device_id(self):
        return "did"

    async def get_authorization(self, user_token):
        return "auth"

    async def get_credential(self, authorization):
        return type("Cred", (), {"cred": "c", "token": "t"})()

    def _signed_headers(self, url, method, body, cred, did):
        return {}

    async def _request(self, method, url, headers=None, json_data=None, content=None):
        self.urls.append(url)
        return self._pages.pop(0)


@pytest.mark.anyio
async def test_fetch_official_never_exceeds_page_size_ten():
    fake = _FakeSkland(
        [
            {"code": 0, "data": {"list": [], "hasMore": False, "pageToken": ""}},
        ]
    )

    await fetch_official(fake, "tok")

    assert "pageSize=10" in fake.urls[0]


@pytest.mark.anyio
async def test_fetch_official_raises_on_business_error():
    fake = _FakeSkland([{"code": 10001, "message": "参数错误"}])

    with pytest.raises(FeedError, match="参数错误"):
        await fetch_official(fake, "tok")
```

`srv` 侧需要 `anyio` 后端夹具；在 `server/tests/conftest.py` 新建：

```python
# server/tests/conftest.py
"""Shared pytest fixtures."""

import pytest


@pytest.fixture
def anyio_backend():
    """Run async tests on asyncio only."""
    return "asyncio"
```

- [ ] **Step 6: 运行全部服务端测试**

Run: `cd server && /Users/coe/project/AstrBot/.venv/bin/python -m pytest tests -q`
Expected: PASS（8 passed）

- [ ] **Step 7: 提交**

```bash
git add server/app/feed.py server/tests/test_feed.py server/tests/conftest.py
git commit -m "feat(server): fetch and normalise the skland official column"
```

---

## Task 3: 轮询缓存

**Files:**
- Create: `server/app/cache.py`
- Test: `server/tests/test_cache.py`

**Interfaces:**
- Consumes: `app.feed.fetch_official`、`app.settings.Settings`
- Produces:
  - `class FeedCache`，构造 `FeedCache(settings, fetcher=None)`，其中 `fetcher` 是可注入的 `async () -> list[dict]`
  - `async def refresh(self) -> bool` —— 成功返回 `True`，失败记录错误并返回 `False`
  - `def items(self) -> list[dict]`
  - `def snapshot(self) -> dict[str, Any]` —— `{"items": [...], "last_success_at": int, "last_error": str, "stale": bool}`
  - `def is_stale(self, now: int | None = None) -> bool`
  - `async def run_forever(self) -> None`

- [ ] **Step 1: 写失败的测试**

```python
# server/tests/test_cache.py
"""The cache must survive upstream failures without losing its last good payload."""

import pytest

from app.cache import FeedCache
from app.settings import Settings


def _settings(**overrides):
    base = dict(
        api_key="k",
        credential_file="/tmp/c.json",
        state_file="/tmp/s.json",
        host="127.0.0.1",
        port=8788,
        poll_interval_seconds=600,
        window_hours=72,
        stale_minutes=60,
    )
    base.update(overrides)
    return Settings(**base)


@pytest.mark.anyio
async def test_refresh_stores_items_and_timestamp():
    async def fetcher():
        return [{"id": "1", "title": "t"}]

    cache = FeedCache(_settings(), fetcher=fetcher)

    assert await cache.refresh() is True
    snapshot = cache.snapshot()
    assert snapshot["items"] == [{"id": "1", "title": "t"}]
    assert snapshot["last_success_at"] > 0
    assert snapshot["last_error"] == ""


@pytest.mark.anyio
async def test_failed_refresh_keeps_last_good_items_and_records_error():
    calls = {"n": 0}

    async def fetcher():
        calls["n"] += 1
        if calls["n"] == 1:
            return [{"id": "1", "title": "t"}]
        raise RuntimeError("boom")

    cache = FeedCache(_settings(), fetcher=fetcher)

    await cache.refresh()
    assert await cache.refresh() is False

    snapshot = cache.snapshot()
    assert snapshot["items"] == [{"id": "1", "title": "t"}]
    assert "boom" in snapshot["last_error"]
    assert snapshot["last_success_at"] > 0


@pytest.mark.anyio
async def test_is_stale_uses_last_success_age():
    async def fetcher():
        return [{"id": "1"}]

    cache = FeedCache(_settings(stale_minutes=60), fetcher=fetcher)
    await cache.refresh()

    assert cache.is_stale(now=cache.snapshot()["last_success_at"] + 59 * 60) is False
    assert cache.is_stale(now=cache.snapshot()["last_success_at"] + 61 * 60) is True


def test_is_stale_when_never_refreshed():
    cache = FeedCache(_settings(), fetcher=None)

    assert cache.snapshot()["last_success_at"] == 0
    assert cache.is_stale() is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd server && /Users/coe/project/AstrBot/.venv/bin/python -m pytest tests/test_cache.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.cache'`

- [ ] **Step 3: 写实现**

```python
# server/app/cache.py
"""Hold the newest official feed in memory and refresh it in the background.

Every plugin instance talks to this service instead of to Skland, so the number
of upstream requests stays constant no matter how many users install the plugin.
A failed refresh keeps the previous payload: a stale answer beats no answer, and
``last_success_at`` lets the caller decide when stale is too stale.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

from .settings import Settings

logger = logging.getLogger(__name__)

Fetcher = Callable[[], Awaitable[list[dict[str, Any]]]]


class FeedCache:
    """In-memory cache of the official feed."""

    def __init__(self, settings: Settings, fetcher: Fetcher | None = None) -> None:
        """Initialize the cache.

        Args:
            settings: Service settings.
            fetcher: Coroutine producing fresh records; injected by tests.
        """
        self.settings = settings
        self._fetcher = fetcher
        self._items: list[dict[str, Any]] = []
        self._last_success_at = 0
        self._last_error = ""

    def items(self) -> list[dict[str, Any]]:
        """Return the cached records.

        Returns:
            The current record list, newest first.
        """
        return list(self._items)

    def is_stale(self, now: int | None = None) -> bool:
        """Report whether the cache is older than the configured limit.

        Args:
            now: Unix seconds to compare against; defaults to the clock.

        Returns:
            ``True`` when never refreshed or past ``stale_minutes``.
        """
        if self._last_success_at <= 0:
            return True
        reference = int(now if now is not None else time.time())
        return reference - self._last_success_at > self.settings.stale_minutes * 60

    def snapshot(self) -> dict[str, Any]:
        """Describe the cache for the HTTP layer.

        Returns:
            Mapping with ``items``, ``last_success_at``, ``last_error`` and
            ``stale``.
        """
        return {
            "items": self.items(),
            "last_success_at": self._last_success_at,
            "last_error": self._last_error,
            "stale": self.is_stale(),
        }

    async def refresh(self) -> bool:
        """Fetch fresh records.

        Returns:
            ``True`` when the refresh succeeded, ``False`` otherwise. The
            previous payload is preserved on failure.
        """
        fetcher = self._fetcher
        if fetcher is None:
            return False
        try:
            records = await fetcher()
        except Exception as exc:  # noqa: BLE001 - reported through the endpoint
            self._last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("feed refresh failed: %s", self._last_error)
            return False

        self._items = list(records)
        self._last_success_at = int(time.time())
        self._last_error = ""
        logger.info("feed refreshed: %d items", len(self._items))
        return True

    async def run_forever(self) -> None:
        """Refresh on a fixed interval until cancelled."""
        while True:
            await self.refresh()
            try:
                await asyncio.sleep(self.settings.poll_interval_seconds)
            except asyncio.CancelledError:
                raise
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd server && /Users/coe/project/AstrBot/.venv/bin/python -m pytest tests/test_cache.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add server/app/cache.py server/tests/test_cache.py
git commit -m "feat(server): cache the official feed with staleness tracking"
```

---

## Task 4: HTTP 接口与鉴权

**Files:**
- Create: `server/app/credentials.py`
- Create: `server/app/main.py`
- Test: `server/tests/test_api.py`

**Interfaces:**
- Consumes: `FeedCache`、`Settings`、`app.feed.fetch_official`、`app.skland_client.SklandClient`
- Produces:
  - `app.credentials.load_user_token(path: Path) -> str`、`save_user_token(path: Path, token: str) -> None`
  - `app.main.create_app(settings: Settings | None = None, cache: FeedCache | None = None) -> FastAPI`
  - `app.main.build_fetcher(settings: Settings) -> Fetcher`
  - 端点 `GET /api/ark/v1/feed`、`GET /api/ark/v1/health`

- [ ] **Step 1: 写失败的测试**

```python
# server/tests/test_api.py
"""The HTTP surface: API-key gate plus a stable response envelope."""

import httpx
import pytest

from app.cache import FeedCache
from app.main import create_app
from app.settings import Settings


def _settings(**overrides):
    base = dict(
        api_key="secret",
        credential_file="/tmp/c.json",
        state_file="/tmp/s.json",
        host="127.0.0.1",
        port=8788,
        poll_interval_seconds=600,
        window_hours=72,
        stale_minutes=60,
    )
    base.update(overrides)
    return Settings(**base)


def _client(cache, settings):
    app = create_app(settings=settings, cache=cache)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.anyio
async def test_feed_requires_api_key():
    async def fetcher():
        return []

    cache = FeedCache(_settings(), fetcher=fetcher)
    async with _client(cache, _settings()) as client:
        response = await client.get("/api/ark/v1/feed")

    assert response.status_code == 401
    assert response.json()["code"] == 401


@pytest.mark.anyio
async def test_feed_rejects_wrong_api_key():
    async def fetcher():
        return []

    cache = FeedCache(_settings(), fetcher=fetcher)
    async with _client(cache, _settings()) as client:
        response = await client.get("/api/ark/v1/feed", headers={"X-API-Key": "nope"})

    assert response.status_code == 401


@pytest.mark.anyio
async def test_feed_returns_items_with_valid_key():
    async def fetcher():
        return [{"id": "1", "title": "t", "published_at": 100}]

    cache = FeedCache(_settings(), fetcher=fetcher)
    await cache.refresh()
    async with _client(cache, _settings()) as client:
        response = await client.get("/api/ark/v1/feed", headers={"X-API-Key": "secret"})

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["items"] == [{"id": "1", "title": "t", "published_at": 100}]
    assert body["data"]["stale"] is False


@pytest.mark.anyio
async def test_health_is_not_gated_and_reports_staleness():
    async def fetcher():
        return []

    cache = FeedCache(_settings(), fetcher=fetcher)
    async with _client(cache, _settings()) as client:
        response = await client.get("/api/ark/v1/health")

    assert response.status_code == 200
    assert response.json()["data"]["stale"] is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd server && /Users/coe/project/AstrBot/.venv/bin/python -m pytest tests/test_api.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: 写实现**

```python
# server/app/credentials.py
"""Read and write the long-lived Hypergryph passport token.

The token is what a one-time QR login produces; short-lived Skland credentials
are minted from it on demand and never persisted.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def load_user_token(path: Path) -> str:
    """Read the stored passport token.

    Args:
        path: Credential file written by ``scripts/login.py``.

    Returns:
        The token, or an empty string when absent or unreadable.
    """
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("user_token") or "")


def save_user_token(path: Path, token: str) -> None:
    """Persist the passport token with owner-only permissions.

    Args:
        path: Destination file.
        token: Passport token to store.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps({"user_token": token}, ensure_ascii=False), encoding="utf-8"
    )
    os.chmod(destination, 0o600)
```

```python
# server/app/main.py
"""FastAPI surface of the aggregator.

Two endpoints: ``/api/ark/v1/feed`` for the plugin (API-key gated) and
``/api/ark/v1/health`` for monitoring (open, exposes no content).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Awaitable

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from .cache import FeedCache
from .credentials import load_user_token
from .feed import fetch_official
from .settings import Settings
from .skland_client import SklandClient

logger = logging.getLogger(__name__)

Fetcher = Any


def build_fetcher(settings: Settings) -> Any:
    """Create the coroutine used to refresh the cache.

    Args:
        settings: Service settings.

    Returns:
        An async callable returning normalised records.

    Raises:
        RuntimeError: When no passport token has been provisioned yet.
    """

    async def fetcher() -> list[dict[str, Any]]:
        token = load_user_token(settings.credential_file)
        if not token:
            raise RuntimeError("尚未登录：请先运行 scripts/login.py 扫码获取凭证")
        client = SklandClient()
        try:
            return await fetch_official(
                client, token, window_hours=settings.window_hours
            )
        finally:
            await client.close()

    return fetcher


def create_app(
    settings: Settings | None = None,
    cache: FeedCache | None = None,
) -> FastAPI:
    """Build the FastAPI application.

    Args:
        settings: Service settings; read from the environment when omitted.
        cache: Pre-built cache, used by tests.

    Returns:
        The configured application.
    """
    resolved = settings or Settings.from_env()
    feed_cache = cache or FeedCache(resolved, fetcher=build_fetcher(resolved))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(feed_cache.run_forever())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    app = FastAPI(title="arksource", version="1.0.0", lifespan=lifespan)
    app.state.cache = feed_cache
    app.state.settings = resolved

    @app.get("/api/ark/v1/health")
    async def health() -> dict[str, Any]:
        """Report cache freshness without exposing content."""
        snapshot = feed_cache.snapshot()
        return {
            "code": 0,
            "data": {
                "stale": snapshot["stale"],
                "count": len(snapshot["items"]),
                "last_success_at": snapshot["last_success_at"],
                "last_error": snapshot["last_error"],
            },
        }

    @app.get("/api/ark/v1/feed")
    async def feed(request: Request, x_api_key: str = Header(default="")):
        """Return the normalised official feed."""
        expected = resolved.api_key
        if not expected or x_api_key != expected:
            return JSONResponse(
                status_code=401,
                content={"code": 401, "message": "缺少或无效的 X-API-Key"},
            )
        snapshot = feed_cache.snapshot()
        return {
            "code": 0,
            "data": {
                "items": snapshot["items"],
                "stale": snapshot["stale"],
                "last_success_at": snapshot["last_success_at"],
                "last_error": snapshot["last_error"],
            },
        }

    return app


app = create_app()
```

`server/app/__main__.py`（让 `python -m app` 能起服务）：

```python
# server/app/__main__.py
"""Run the aggregator with uvicorn."""

import uvicorn

from .settings import Settings


def main() -> None:
    """Start the HTTP server on the configured host and port."""
    settings = Settings.from_env()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd server && /Users/coe/project/AstrBot/.venv/bin/python -m pytest tests/test_api.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: 运行全部服务端测试**

Run: `cd server && /Users/coe/project/AstrBot/.venv/bin/python -m pytest tests -q`
Expected: PASS（16 passed）

- [ ] **Step 6: 提交**

```bash
git add server/app/credentials.py server/app/main.py server/app/__main__.py server/tests/test_api.py
git commit -m "feat(server): expose api-key gated feed endpoint"
```

---

## Task 5: 一次性扫码登录脚本

**Files:**
- Create: `server/scripts/login.py`
- Test: 手工验收（依赖真人扫码，不做自动化测试）

**Interfaces:**
- Consumes: `app.hypergryph_client.HypergryphClient`（`create_qr()` → `{"scan_id", "scan_url"}`、`poll_qr(scan_id)` → `scan_code | None`、`get_token_by_scan_code(scan_code)` → `token`）、`app.credentials.save_user_token`
- Produces: `server/scripts/login.py` 可执行，把 `user_token` 写入 `--output`（默认取 `ARKSOURCE_CREDENTIAL_FILE`）

- [ ] **Step 1: 写脚本**

```python
# server/scripts/login.py
"""One-time Skland QR login for the aggregator.

Run it on the host that serves the aggregator, scan the printed QR with the
森空岛 app, and the long-lived passport token is written to the credential file.
The token only needs replacing if the account logs out or the token is revoked.

Usage:
    python scripts/login.py [--output /opt/arksource/credentials.json]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.credentials import save_user_token  # noqa: E402
from app.hypergryph_client import HypergryphClient  # noqa: E402

POLL_INTERVAL_SECONDS = 2
POLL_TIMEOUT_SECONDS = 180


def render_qr(text: str) -> None:
    """Print a QR code for the given payload to the terminal.

    Args:
        text: Payload to encode, here the ``hypergryph://`` login URL.
    """
    try:
        import qrcode
    except ImportError:
        print("未安装 qrcode，无法在终端渲染二维码。")
        print("请在能生成二维码的工具里手工编码下面的内容：")
        print(text)
        return
    qr = qrcode.QRCode(border=1)
    qr.add_data(text)
    qr.make(fit=True)
    qr.print_ascii(invert=True)


async def main() -> int:
    """Run the QR login flow.

    Returns:
        Process exit code: 0 on success, 1 on timeout or failure.
    """
    parser = argparse.ArgumentParser(description="Skland QR login for arksource")
    parser.add_argument(
        "--output",
        default=os.environ.get(
            "ARKSOURCE_CREDENTIAL_FILE", "/opt/arksource/credentials.json"
        ),
        help="credential file to write",
    )
    args = parser.parse_args()

    client = HypergryphClient()
    try:
        qr = await client.create_qr()
        print("请使用「森空岛」APP 扫描下面的二维码：\n")
        render_qr(qr["scan_url"])
        print(f"\nscan_id={qr['scan_id']}\n等待扫码…")

        waited = 0
        while waited < POLL_TIMEOUT_SECONDS:
            scan_code = await client.poll_qr(qr["scan_id"])
            if scan_code:
                token = await client.get_token_by_scan_code(scan_code)
                save_user_token(Path(args.output), token)
                print(f"登录成功，凭证已写入 {args.output}")
                return 0
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            waited += POLL_INTERVAL_SECONDS

        print("等待扫码超时，请重新运行本脚本。")
        return 1
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

- [ ] **Step 2: 本地语法检查**

Run: `cd server && /Users/coe/project/AstrBot/.venv/bin/python -m py_compile scripts/login.py && echo ok`
Expected: 输出 `ok`

- [ ] **Step 3: 部署后在 HK 上实跑（Task 6 完成后执行）**

Run: `ssh HK '/opt/arksource/venv/bin/python /opt/arksource/scripts/login.py'`
Expected: 终端出现二维码 → 用森空岛 APP 扫码 → 输出「登录成功，凭证已写入 …」

- [ ] **Step 4: 提交**

```bash
git add server/scripts/login.py
git commit -m "feat(server): add one-time skland qr login script"
```

---

## Task 6: 部署到 HK 并线上验证

**Files:**
- Create: `server/deploy/arksource.service`
- Create: `server/deploy/caddy-snippet.txt`
- Create: `server/README.md`

**Interfaces:**
- Consumes: 前五个任务的产物
- Produces: 线上可用的 `https://ark.youyou.ink/api/ark/v1/feed`

- [ ] **Step 1: 写 systemd unit**

```ini
# server/deploy/arksource.service
[Unit]
Description=Arknights announcement aggregator (arknights AstrBot plugin)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/arksource
EnvironmentFile=/opt/arksource/arksource.env
ExecStart=/opt/arksource/venv/bin/python -m app
Restart=always
RestartSec=5
User=root
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: 写 Caddy 片段**

```text
# server/deploy/caddy-snippet.txt
# Append this as a new site block at the END of /etc/caddy/Caddyfile. It is a
# dedicated host, so nothing else matches it and no path prefix is needed —
# Caddy issues the certificate for ark.youyou.ink on first request.
#
# Requires a DNS A record: ark.youyou.ink -> 162.211.183.29
ark.youyou.ink {
	encode zstd gzip
	reverse_proxy 127.0.0.1:8788 {
		header_up X-Forwarded-Proto https
	}
}
```

- [ ] **Step 3: 写部署说明**

```markdown
<!-- server/README.md -->
# arksource —— 明日方舟官方动态聚合服务

为 `astrbot_plugin_arknights` 提供「官方动态」数据的自建源。持有一份森空岛凭证，
后台轮询「官方」栏目并缓存，插件使用者无需任何鹰角账号。

## 为什么需要它

森空岛内容接口必须登录，且每个插件实例各自轮询会给上游带来成倍压力。
服务端集中缓存后，无论多少用户安装插件，上游只会看到这一台机器。

## 部署

```bash
# 1. 代码
mkdir -p /opt/arksource && cd /opt/arksource
# 把仓库的 server/ 内容放到这里（rsync 或 git clone 后拷贝）

# 2. 依赖
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

# 3. 配置
cat > arksource.env <<'EOF'
ARKSOURCE_API_KEY=<用 openssl rand -hex 24 生成>
ARKSOURCE_HOST=127.0.0.1
ARKSOURCE_PORT=8788
ARKSOURCE_CREDENTIAL_FILE=/opt/arksource/credentials.json
ARKSOURCE_POLL_INTERVAL=600
ARKSOURCE_WINDOW_HOURS=72
ARKSOURCE_STALE_MINUTES=60
EOF
chmod 600 arksource.env

# 4. 扫码登录（用森空岛 APP 扫终端二维码）
./venv/bin/python scripts/login.py

# 5. 服务
cp deploy/arksource.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now arksource

# 6. 反代：给 ark.youyou.ink 配 A 记录指向 162.211.183.29，再把
#    deploy/caddy-snippet.txt 的站点块追加到 /etc/caddy/Caddyfile 末尾
caddy validate --config /etc/caddy/Caddyfile && systemctl reload caddy
```

## 验证

```bash
curl -s localhost:8788/api/ark/v1/health
curl -s -H "X-API-Key: $ARKSOURCE_API_KEY" localhost:8788/api/ark/v1/feed | head -c 400
curl -s -H "X-API-Key: $ARKSOURCE_API_KEY" https://ark.youyou.ink/api/ark/v1/feed | head -c 400
```

## 接口

| 方法 | 路径 | 鉴权 | 说明 |
|:--|:--|:--|:--|
| GET | `/api/ark/v1/feed` | `X-API-Key` | 官方栏目条目，最新在前 |
| GET | `/api/ark/v1/health` | 无 | 缓存新鲜度，不含内容 |

`data.items[]` 字段：`id`、`title`、`kind`(1 视频 / 2 图集 / 3 文章)、
`published_at`(unix 秒)、`cover`、`images[]`、`text`、`url`、`tags[]`。

## 维护

- 凭证失效（接口持续报 `用户未登录`）：重跑 `scripts/login.py`。
- `core/skland.py` 或 `core/hypergryph.py` 变更后，用 `cp` 重新覆盖
  `app/skland_client.py` / `app/hypergryph_client.py`，并重启服务。
- `stale` 长时间为 `true`：看 `journalctl -u arksource -n 50`。
```

- [ ] **Step 4: 上传并部署到 HK**

```bash
# 本地：把 server/ 同步过去（排除本地 venv 与缓存）
rsync -az --delete --exclude venv --exclude __pycache__ \
  server/ root@162.211.183.29:/opt/arksource/

# 远端：依赖 + 配置
ssh HK 'cd /opt/arksource && python3 -m venv venv && ./venv/bin/pip install -q -r requirements.txt'
ssh HK 'cd /opt/arksource && printf "ARKSOURCE_API_KEY=%s\nARKSOURCE_HOST=127.0.0.1\nARKSOURCE_PORT=8788\nARKSOURCE_CREDENTIAL_FILE=/opt/arksource/credentials.json\nARKSOURCE_POLL_INTERVAL=600\nARKSOURCE_WINDOW_HOURS=72\nARKSOURCE_STALE_MINUTES=60\n" "$(openssl rand -hex 24)" > arksource.env && chmod 600 arksource.env && cat arksource.env'
```

**把输出的 `ARKSOURCE_API_KEY` 记下来**——Task 9 要把它写进插件配置的默认值。

- [ ] **Step 5: 扫码登录**

Run: `ssh -t HK '/opt/arksource/venv/bin/python /opt/arksource/scripts/login.py'`
Expected: 终端出现二维码，手机扫码后输出「登录成功，凭证已写入 /opt/arksource/credentials.json」

- [ ] **Step 6: 起服务并本地验证**

```bash
ssh HK 'cp /opt/arksource/deploy/arksource.service /etc/systemd/system/ && systemctl daemon-reload && systemctl enable --now arksource && sleep 20 && systemctl is-active arksource'
ssh HK 'curl -s localhost:8788/api/ark/v1/health; echo'
```

Expected: `active`；health 返回 `"code":0`，稍后 `"count"` > 0 且 `"stale":false`。
若 `count` 为 0，先看 `journalctl -u arksource -n 50`（最常见原因是凭证文件缺失或 token 无效）。

- [ ] **Step 7: 接入 Caddy 并公网验证**

**前置**：确认 `ark.youyou.ink` 的 A 记录已指向 `162.211.183.29`（由人工在 DNS 服务商配置）。先验证解析再动 Caddy：

```bash
getent hosts ark.youyou.ink
```

Expected: 输出 `162.211.183.29  ark.youyou.ink`。若为空，停下并请人工确认 DNS 记录。

把 `deploy/caddy-snippet.txt` 的站点块追加到 `/etc/caddy/Caddyfile` 末尾：

```bash
ssh HK 'cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak-$(date +%Y%m%d-%H%M%S)'
ssh HK 'python3 - <<'"'"'PY'"'"'
from pathlib import Path
p = Path("/etc/caddy/Caddyfile")
text = p.read_text(encoding="utf-8")
if "ark.youyou.ink" in text:
    print("already present")
else:
    block = (
        "\nark.youyou.ink {\n"
        "\tencode zstd gzip\n"
        "\treverse_proxy 127.0.0.1:8788 {\n"
        "\t\theader_up X-Forwarded-Proto https\n"
        "\t}\n"
        "}\n"
    )
    if not text.endswith("\n"):
        text += "\n"
    p.write_text(text + block, encoding="utf-8")
    print("appended")
PY'
ssh HK 'caddy validate --config /etc/caddy/Caddyfile && systemctl reload caddy && echo reloaded'
```

公网验证（把 `<KEY>` 换成 Step 4 记下的 key；首次请求 Caddy 会即时签发证书，可能多等几秒）：

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://ark.youyou.ink/api/ark/v1/feed                # 期望 401
curl -s -H "X-API-Key: <KEY>" https://ark.youyou.ink/api/ark/v1/feed | head -c 500              # 期望 code:0 且 items 非空
```

- [ ] **Step 8: 提交**

```bash
git add server/deploy/ server/README.md
git commit -m "feat(server): deployment units, caddy snippet and runbook"
```

---

# Phase B：插件端

## Task 7: 自建源客户端

**Files:**
- Create: `core/feed.py`
- Test: `tests/test_feed.py`

**Interfaces:**
- Consumes: 服务端 `GET /api/ark/v1/feed`（见 Task 4）
- Produces:
  - `class FeedError(Exception)`
  - `class FeedClient`，构造 `FeedClient(base_url: str, api_key: str, client: httpx.AsyncClient | None = None)`
  - `async def fetch(self) -> list[dict[str, Any]]` —— 返回与 `core.announce.AnnounceClient.fetch()` **同构**的记录：`id`、`title`、`author`、`brief`、`group`、`group_cn`、`url`、`ts`、`date_text`、`text`、`images`、`image_total`、`body_html`、`kind`、`cover`、`stale`
  - `async def close(self) -> None`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_feed.py
"""The self-hosted feed client normalises into the website record shape."""

import httpx
import pytest

from core.feed import FeedClient, FeedError


def _client(handler, base_url="https://ark.youyou.ink/api/ark/v1", api_key="k"):
    transport = httpx.MockTransport(handler)
    return FeedClient(
        base_url=base_url,
        api_key=api_key,
        client=httpx.AsyncClient(transport=transport),
    )


@pytest.mark.anyio
async def test_fetch_normalises_into_announce_shape():
    def handler(request):
        assert request.headers["X-API-Key"] == "k"
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "stale": False,
                    "items": [
                        {
                            "id": "6377378",
                            "title": "《明日方舟》「书行山海」特别公益PV",
                            "kind": 1,
                            "published_at": 1791709243,
                            "cover": "https://bbs.hycdn.cn/cover.webp",
                            "images": ["https://bbs.hycdn.cn/cover.webp"],
                            "text": "书页翻过山海，故事走向四方。",
                            "url": "https://www.skland.com/article?id=6377378",
                            "tags": ["明日方舟"],
                        }
                    ],
                },
            },
        )

    client = _client(handler)
    records = await client.fetch()
    await client.close()

    assert len(records) == 1
    record = records[0]
    assert record["id"] == "6377378"
    assert record["ts"] == 1791709243
    assert record["kind"] == 1
    assert record["group_cn"] == "官方"
    assert record["cover"] == "https://bbs.hycdn.cn/cover.webp"
    assert record["images"] == ["https://bbs.hycdn.cn/cover.webp"]
    assert record["image_total"] == 1
    assert record["text"] == "书页翻过山海，故事走向四方。"
    assert "书页翻过山海" in record["body_html"]
    assert record["stale"] is False
    # The website record carries a display date; the feed must supply one too.
    assert record["date_text"]


@pytest.mark.anyio
async def test_fetch_raises_on_http_error():
    def handler(request):
        return httpx.Response(500)

    client = _client(handler)
    with pytest.raises(FeedError):
        await client.fetch()
    await client.close()


@pytest.mark.anyio
async def test_fetch_raises_on_401():
    def handler(request):
        return httpx.Response(401, json={"code": 401, "message": "缺少或无效的 X-API-Key"})

    client = _client(handler)
    with pytest.raises(FeedError, match="X-API-Key"):
        await client.fetch()
    await client.close()


@pytest.mark.anyio
async def test_fetch_raises_on_business_error_code():
    def handler(request):
        return httpx.Response(200, json={"code": 500, "message": "服务内部错误"})

    client = _client(handler)
    with pytest.raises(FeedError, match="服务内部错误"):
        await client.fetch()
    await client.close()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `/Users/coe/project/AstrBot/.venv/bin/python -m pytest tests/test_feed.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.feed'`

- [ ] **Step 3: 写实现**

```python
# core/feed.py
"""Self-hosted Arknights official feed (森空岛「官方」栏目).

The aggregator behind this client holds a single Skland credential, so plugin
users need no Hypergryph account of their own. Records are normalised into the
exact shape :meth:`core.announce.AnnounceClient.fetch` returns, which lets the
push job, the renderer and the templates stay source-agnostic.
"""

from __future__ import annotations

import html as html_module
from datetime import datetime
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://ark.youyou.ink/api/ark/v1"
FEED_PATH = "/feed"
GROUP_CN = "官方"
GROUP_KEY = "OFFICIAL"


class FeedError(Exception):
    """Raised when the self-hosted feed cannot be read."""


def _format_time(stamp: Any) -> str:
    """Render a unix timestamp the way the website source does.

    Args:
        stamp: Unix seconds.

    Returns:
        ``YYYY-MM-DD HH:MM``, or an empty string when unparsable.
    """
    try:
        return datetime.fromtimestamp(int(stamp)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return ""


def _body_html(text: str, images: list[str]) -> str:
    """Build the card body from plain text plus images.

    Args:
        text: Body text from the aggregator.
        images: Image URLs, cover first.

    Returns:
        HTML fragment understood by ``announce_detail.html``.
    """
    parts: list[str] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            parts.append(f"<p>{html_module.escape(line)}</p>")
    for url in images:
        parts.append(f'<img src="{html_module.escape(url, quote=True)}" />')
    return "".join(parts)


class FeedClient:
    """Reads the self-hosted official feed."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str = "",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize the client.

        Args:
            base_url: Aggregator base URL, without the trailing ``/feed``.
            api_key: Value sent as ``X-API-Key``.
            client: Optional pre-built HTTP client, used by tests.
        """
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key
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
            self._client = httpx.AsyncClient(
                timeout=20.0,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; AstrBot-Arknights)"},
            )
            self._owns_client = True
        return self._client

    async def fetch(self) -> list[dict[str, Any]]:
        """Fetch the official feed.

        Returns:
            Records newest first, in the website source's shape.

        Raises:
            FeedError: On transport failure, a non-2xx status, a non-zero
                business code, or a malformed payload.
        """
        url = f"{self.base_url}{FEED_PATH}"
        try:
            response = await self._get_client().get(
                url, headers={"X-API-Key": self.api_key}
            )
        except httpx.HTTPError as exc:
            raise FeedError(f"自建源请求失败: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise FeedError(f"自建源响应格式异常: HTTP {response.status_code}") from exc

        message = ""
        if isinstance(payload, dict):
            message = str(payload.get("message") or "")
        if response.status_code >= 400:
            raise FeedError(message or f"自建源请求失败: HTTP {response.status_code}")
        if not isinstance(payload, dict) or payload.get("code") not in (0, None):
            raise FeedError(message or "自建源返回错误")

        data = payload.get("data")
        if not isinstance(data, dict):
            raise FeedError("自建源响应缺少 data")
        items = data.get("items")
        if not isinstance(items, list):
            raise FeedError("自建源响应缺少 items")
        stale = bool(data.get("stale"))

        records: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or "")
            if not item_id:
                continue
            images = [str(u) for u in (item.get("images") or []) if u]
            cover = str(item.get("cover") or "")
            ordered = ([cover] if cover else []) + [u for u in images if u != cover]
            text = str(item.get("text") or "")
            published = item.get("published_at") or 0
            records.append(
                {
                    "id": item_id,
                    "title": str(item.get("title") or item_id),
                    "author": "明日方舟",
                    "brief": text,
                    "group": GROUP_KEY,
                    "group_cn": GROUP_CN,
                    "url": str(item.get("url") or ""),
                    "ts": int(published or 0),
                    "date_text": _format_time(published),
                    "text": text,
                    "images": ordered,
                    "image_total": len(ordered),
                    "body_html": _body_html(text, ordered),
                    "kind": int(item.get("kind") or 0),
                    "cover": cover,
                    "stale": stale,
                }
            )

        records.sort(key=lambda entry: (entry["ts"], entry["id"]), reverse=True)
        return records
```

- [ ] **Step 4: 运行测试确认通过**

Run: `/Users/coe/project/AstrBot/.venv/bin/python -m pytest tests/test_feed.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add core/feed.py tests/test_feed.py
git commit -m "feat: add self-hosted official feed client"
```

---

## Task 8: 源状态持久化

**Files:**
- Modify: `core/store.py`
- Test: `tests/test_store.py`（新建或追加）

**Interfaces:**
- Consumes: `core.store.Store` 现有的原子写入与 `0600` 约定
- Produces:
  - `async def feed_state(self) -> dict[str, Any]` —— `{"active": "selfhosted" | "official" | ""}`；未设置时 `active` 为 `""`
  - `async def set_feed_active(self, active: str) -> None`

- [ ] **Step 1: 写失败的测试**

**注意**：`tests/test_store.py` **已经存在**（含 `test_upsert_and_get_user` 等用例）。不要覆盖它——把下面两个用例**追加到文件末尾**即可；该文件已经 `import pytest`、`from core.store import Store`，并统一使用 `Store(tmp_path / "users.json")` 的写法。

```python
# 追加到 tests/test_store.py 末尾

@pytest.mark.anyio
async def test_feed_state_defaults_to_empty(tmp_path):
    store = Store(tmp_path / "users.json")

    state = await store.feed_state()

    assert state == {"active": ""}


@pytest.mark.anyio
async def test_set_feed_active_persists(tmp_path):
    path = tmp_path / "users.json"
    store = Store(path)
    await store.set_feed_active("official")

    reopened = Store(path)

    assert (await reopened.feed_state())["active"] == "official"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `/Users/coe/project/AstrBot/.venv/bin/python -m pytest tests/test_store.py -q`
Expected: FAIL — `AttributeError: 'Store' object has no attribute 'feed_state'`

- [ ] **Step 3: 在 `core/store.py` 实现**

`core/store.py` 里的 `_empty()` 定义了存储的全部顶层键，先把 `feed` 加进去：

```python
def _empty() -> dict[str, Any]:
    """Return a freshly initialized store structure."""
    return {
        "users": {},
        "subs": {"sanity": [], "sign_groups": [], "announce": []},
        "announce": {"watermark": 0},
        # ``feed`` records whether the plugin has degraded away from the
        # self-hosted source. It lives here so a restart cannot lose a
        # degradation that is in progress. ``""`` means "not degraded".
        "feed": {"active": ""},
    }
```

然后照 `announce_watermark` / `set_announce_watermark` 的写法新增两个方法：

新增方法：

```python
    async def feed_state(self) -> dict[str, Any]:
        """Read the announcement source state.

        Returns:
            Mapping with ``active``: ``"selfhosted"``, ``"official"``, or ``""``
            when the plugin has never degraded.
        """
        data = self._read()
        state = data.get("feed")
        if not isinstance(state, dict):
            return {"active": ""}
        return {"active": str(state.get("active") or "")}

    async def set_feed_active(self, active: str) -> None:
        """Record which source is currently serving pushes.

        Args:
            active: ``"selfhosted"`` or ``"official"``.
        """
        async with self._lock:
            data = self._read()
            state = data.setdefault("feed", {"active": ""})
            state["active"] = str(active)
            self._write(data)
```

**注意**：`core/store.py` 的私有读写方法是 `_read()` / `_write(data)`，且所有写操作都在 `async with self._lock:` 内——照抄上面写法即可。

- [ ] **Step 4: 运行测试确认通过**

Run: `/Users/coe/project/AstrBot/.venv/bin/python -m pytest tests/test_store.py -q`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add core/store.py tests/test_store.py
git commit -m "feat: persist announcement source state"
```

---

## Task 9: 配置项

**Files:**
- Modify: `_conf_schema.json`

**Interfaces:**
- Consumes: 无
- Produces: 配置键 `feed_source`、`feed_base_url`、`feed_api_key`、`feed_exclude_keywords`、`feed_retry_delays`；`main.py` 通过 `self.config.get(<key>, <default>)` 读取

- [ ] **Step 1: 写入配置**

把下面的键并入 `_conf_schema.json`（保持既有键不变）：

```json
  "feed_source": {
    "description": "公告推送数据源",
    "type": "string",
    "enum": ["selfhosted", "official"],
    "default": "selfhosted",
    "hint": "selfhosted = 自建森空岛官方源（含 PV/EP 视频等官网没有的内容）；official = 官网公告源。自建源连续失败会自动降级到官网源"
  },
  "feed_base_url": {
    "description": "自建源地址",
    "type": "string",
    "default": "https://ark.youyou.ink/api/ark/v1",
    "hint": "默认无需修改"
  },
  "feed_api_key": {
    "description": "自建源访问密钥",
    "type": "string",
    "default": "<Task 6 Step 4 生成的 key>",
    "hint": "已内置默认值，无需修改"
  },
  "feed_exclude_keywords": {
    "description": "公告推送排除关键词",
    "type": "string",
    "default": "签到福利,周记表,每日谜题,猜猜我是谁,创作集锦,版区作品,模组,游戏工具,有奖活动,创作者应援,讨论楼,热议",
    "hint": "英文逗号分隔；标题命中任一关键词的条目不会推送。留空则不过滤"
  },
  "feed_retry_delays": {
    "description": "自建源失败后的重试间隔(分钟)",
    "type": "string",
    "default": "1,3,5",
    "hint": "英文逗号分隔。每次轮询发现自建源失败后，按这些间隔依次重试；全部失败才降级到官网源并告警。留空表示失败即降级"
  }
```

**必须把 `"<Task 6 Step 4 生成的 key>"` 替换成 Task 6 Step 4 实际生成的 key**，否则配置默认值不可用。

- [ ] **Step 2: 校验 JSON 合法**

Run: `/Users/coe/project/AstrBot/.venv/bin/python -c "import json;d=json.load(open('_conf_schema.json',encoding='utf-8'));print(sorted(d));assert d['feed_source']['default']=='selfhosted';assert d['feed_api_key']['default'].startswith(('0','1','2','3','4','5','6','7','8','9','a','b','c','d','e','f'))"`
Expected: 打印全部键名且断言通过

- [ ] **Step 3: 提交**

```bash
git add _conf_schema.json
git commit -m "feat: add self-hosted feed configuration"
```

---

## Task 10: 源选择、失败重试与降级告警

**Files:**
- Modify: `main.py`（新增 `_source_records`、`_feed_retry_delays`、`_notify_feed_subscribers`，改 `_announce_poll_job` 的取数调用，改 `initialize`/`terminate` 增加 `_feed` 生命周期）
- Modify: `tests/integration_check.py`

**Interfaces:**
- Consumes: `core.feed.FeedClient`、`FeedError`（Task 7）；`Store.feed_state` / `set_feed_active`（Task 8）；配置键（Task 9）
- Produces:
  - `self._feed: FeedClient`（在 `initialize` 构造，`terminate` 关闭）
  - `def _feed_retry_delays(self) -> list[float]` —— 解析 `feed_retry_delays`，返回单位分钟的浮点列表
  - `async def _source_records(self) -> list[dict[str, Any]]` —— 返回待推送记录；重试与降级都在内部完成
  - `async def _notify_feed_subscribers(self, text: str) -> None`

- [ ] **Step 1: 写失败的集成断言**

在 `tests/integration_check.py` 的 `main()` 内、公告订阅那组断言之后追加。**沿用该文件既有的构造方式**：`plugin_module.ArknightsPlugin(context=..., config=...)`、`plugin.store = Store(Path("/tmp/ak-integration/users.json"))`、以及已有的 `sent` / `capture` 记录发出的消息段。

```python
    # ── 自建源：正常、重试、降级、恢复 ────────────────────────────────────
    SELF_TS = int(time.time()) - 60

    def selfhosted(ident, ts, title, kind=1):
        return {
            "id": ident,
            "title": title,
            "author": "明日方舟",
            "brief": "",
            "group": "OFFICIAL",
            "group_cn": "官方",
            "url": "",
            "ts": ts,
            "date_text": "2026-10-12 11:00",
            "text": "",
            "images": [],
            "image_total": 0,
            "body_html": "",
            "kind": kind,
            "cover": "",
            "stale": False,
        }

    SELF_RECORDS = [selfhosted("6377378", SELF_TS, "《明日方舟》「书行山海」特别公益PV")]
    SITE_RECORDS = [announcement("9999", SELF_TS, "[活动预告] 新活动即将开启")]

    class FakeFeed:
        """FeedClient stand-in that fails its first ``fail_times`` calls."""

        def __init__(self, records, fail_times=0, stale=False):
            self.records = [{**record, "stale": stale} for record in records]
            self.fail_times = fail_times
            self.calls = 0

        async def fetch(self):
            self.calls += 1
            if self.calls <= self.fail_times:
                raise FeedError("连接超时")
            return list(self.records)

        async def close(self):
            return None

    def make_source_plugin(feed, config=None, announce_records=None):
        """Build a plugin wired to the fake feed and an optional fake website."""
        built = plugin_module.ArknightsPlugin(
            context=SimpleNamespace(send_message=capture), config=config or {}
        )
        built.store = Store(Path("/tmp/ak-integration/users.json"))
        built.store.path.unlink(missing_ok=True)
        built._feed = feed
        if announce_records is not None:

            async def fake_site():
                return list(announce_records)

            built._announce.fetch = fake_site
        return built

    def alert_text():
        return " ".join(str(getattr(seg, "text", "")) for grp in sent for seg in grp)

    # 1) 自建源正常：用它，不降级
    sent.clear()
    feeder = FakeFeed(SELF_RECORDS)
    plugin = make_source_plugin(
        feeder, {"feed_source": "selfhosted", "feed_retry_delays": "0"}
    )
    records = await plugin._source_records()
    check("自建源正常时使用自建源", [r["id"] for r in records] == ["6377378"], records)
    check(
        "自建源正常时不降级",
        (await plugin.store.feed_state())["active"] == "",
        await plugin.store.feed_state(),
    )

    # 2) 首次失败、重试成功：不降级、不告警
    sent.clear()
    feeder = FakeFeed(SELF_RECORDS, fail_times=1)
    plugin = make_source_plugin(
        feeder, {"feed_source": "selfhosted", "feed_retry_delays": "0"}
    )
    records = await plugin._source_records()
    check("重试成功后仍用自建源", [r["id"] for r in records] == ["6377378"], records)
    check(
        "重试成功不降级",
        (await plugin.store.feed_state())["active"] == "",
        await plugin.store.feed_state(),
    )
    check("确实发生了一次重试", feeder.calls == 2, feeder.calls)
    check("重试成功不发告警", sent == [], f"{sent}")

    # 3) 重试全部失败：降级 + 告警 + 回落到官网源
    sent.clear()
    feeder = FakeFeed(SELF_RECORDS, fail_times=99)
    plugin = make_source_plugin(
        feeder,
        {"feed_source": "selfhosted", "feed_retry_delays": "0,0"},
        announce_records=SITE_RECORDS,
    )
    await plugin.store.set_announce_sub("2260442041", "coe:GroupMessage:454206542", True)
    records = await plugin._source_records()
    check(
        "重试全部失败后降级到官网源",
        (await plugin.store.feed_state())["active"] == "official",
        await plugin.store.feed_state(),
    )
    check("降级后返回官网源记录", [r["id"] for r in records] == ["9999"], records)
    check("尝试次数 = 首发 1 次 + 重试 2 次", feeder.calls == 3, feeder.calls)
    check("降级向订阅者发出了告警", "降级" in alert_text(), alert_text()[:200])

    # 4) 已降级时自建源恢复：切回并通知
    sent.clear()
    feeder = FakeFeed(SELF_RECORDS)
    plugin = make_source_plugin(
        feeder, {"feed_source": "selfhosted", "feed_retry_delays": "0"}
    )
    await plugin.store.set_feed_active("official")
    await plugin.store.set_announce_sub("2260442041", "coe:GroupMessage:454206542", True)
    records = await plugin._source_records()
    check(
        "恢复后切回自建源",
        (await plugin.store.feed_state())["active"] == "",
        await plugin.store.feed_state(),
    )
    check("恢复后返回自建源记录", [r["id"] for r in records] == ["6377378"], records)
    check("恢复发出了通知", "恢复" in alert_text(), alert_text()[:200])

    # 5) 配置为 official 时完全不碰自建源
    sent.clear()
    feeder = FakeFeed(SELF_RECORDS)
    plugin = make_source_plugin(
        feeder, {"feed_source": "official"}, announce_records=SITE_RECORDS
    )
    records = await plugin._source_records()
    check("feed_source=official 时直接用官网源", [r["id"] for r in records] == ["9999"], records)
    check("feed_source=official 时不请求自建源", feeder.calls == 0, feeder.calls)
```

**实现前必读**：`announcement()`、`capture`、`sent` 都定义在公告推送那组断言里；把本段放在同一个 `main()` 内、`announcement` 定义之后即可共用。`FeedError` 需要在该文件里导入——文件顶部已用 `importlib` 加载插件模块，按既有写法补一行 `from core.feed import FeedError`（该文件把仓库根加进了 `sys.path`）。

- [ ] **Step 2: 运行集成检查确认失败**

Run: `/Users/coe/project/AstrBot/.venv/bin/python tests/integration_check.py`
Expected: FAIL —— 报 `AttributeError: 'ArknightsPlugin' object has no attribute '_source_records'`（或缺少 `_feed_retry_delays`）

- [ ] **Step 3: 在 `main.py` 实现**

顶部导入：

```python
from .core.feed import DEFAULT_BASE_URL, FeedClient, FeedError
```

`initialize` 中构造（与既有 `self._announce = AnnounceClient()` 相邻）：

```python
        # The self-hosted source is preferred; the website source stays as the
        # fallback and is also what `feed_source: official` selects outright.
        self._feed = FeedClient(
            base_url=str(self.config.get("feed_base_url") or DEFAULT_BASE_URL),
            api_key=str(self.config.get("feed_api_key") or ""),
        )
```

`terminate` 中关闭（与 `await self._announce.close()` 相邻）：

```python
        await self._feed.close()
```

新增方法（放在 `_announce_records` 之后）：

```python
    # ── 数据源选择、失败重试与降级 ────────────────────────────────────────

    def _is_excluded(self, title: str) -> bool:
        """Report whether a title matches the configured exclusion keywords.

        Args:
            title: Announcement title.

        Returns:
            ``True`` when the title contains any configured keyword.
        """
        raw = str(self.config.get("feed_exclude_keywords") or "")
        keywords = [part.strip() for part in raw.split(",") if part.strip()]
        if not keywords:
            return False
        return any(keyword in (title or "") for keyword in keywords)

    def _feed_retry_delays(self) -> list[float]:
        """Parse the retry schedule used after a self-hosted source failure.

        Returns:
            Delays in minutes, in order; empty when retries are disabled.
        """
        raw = str(self.config.get("feed_retry_delays") or "")
        delays: list[float] = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                delays.append(max(0.0, float(part)))
            except ValueError:
                continue
        return delays

    async def _source_records(self) -> list[dict[str, Any]]:
        """Fetch records from the active source.

        The self-hosted source is preferred. A failed poll is retried on the
        configured schedule, and only when every retry fails does the plugin
        degrade to the website source and tell the subscribers. While degraded
        it re-probes the self-hosted source on each poll and switches back as
        soon as that source recovers.

        Returns:
            Records to push, newest first.

        Raises:
            AnnounceError: When the website source itself cannot be read.
        """
        configured = str(self.config.get("feed_source") or "selfhosted")
        state = await self.store.feed_state()

        if configured == "official":
            return await self._announce_records()

        if state["active"] == "official":
            # Degraded: the probe is cheap and the payload is cached upstream, so
            # it runs on every poll; any failure just keeps serving the website.
            try:
                records = await self._feed.fetch()
            except FeedError:
                return await self._announce_records()
            if records and all(item.get("stale") for item in records):
                return await self._announce_records()
            await self.store.set_feed_active("")
            await self._notify_feed_subscribers("自建公告源已恢复，推送切回自建源。")
            return records

        delays = self._feed_retry_delays()
        last_error = "未知错误"
        for attempt in range(len(delays) + 1):
            try:
                records = await self._feed.fetch()
            except FeedError as exc:
                last_error = str(exc)
            else:
                if not (records and all(item.get("stale") for item in records)):
                    return records
                last_error = "自建源数据过期"

            if attempt < len(delays):
                logger.warning(
                    "[公告轮询] 自建源第 %d 次失败（%s），%.0f 分钟后重试",
                    attempt + 1,
                    last_error,
                    delays[attempt],
                )
                await asyncio.sleep(delays[attempt] * 60)

        # Every attempt failed: degrade, and say so exactly once.
        await self.store.set_feed_active("official")
        await self._notify_feed_subscribers(
            f"自建公告源连续 {len(delays) + 1} 次获取失败，已自动降级到官网公告源。\n"
            f"原因：{last_error}"
        )
        return await self._announce_records()

    async def _notify_feed_subscribers(self, text: str) -> None:
        """Send a source-status notice to every announcement subscriber.

        Args:
            text: Notice body.
        """
        for sub in await self.store.list_announce_subs():
            umo = str(sub.get("umo") or "")
            if umo:
                await self._notify(umo, text)
```

在 `_announce_poll_job` 中把取数换成（重试与降级都包在 `_source_records` 里，`_announce_poll_job` 不需要知道当前用的是哪个源）：

```python
        try:
            records = await self._source_records()
        except AnnounceError as exc:
            logger.warning("[公告轮询] 获取失败: %s", exc)
            return
        if not records:
            return
```

**不需要额外的健康探测任务。** 重试是在 `_source_records` 内按 `feed_retry_delays` 就地等待并重试的，全在同一次轮询里完成：默认 `1,3,5` 合计 9 分钟，远小于 30 分钟的轮询间隔，而该任务已设 `max_instances=1`，下一次轮询不会与它重叠。

**注意**：`asyncio` 必须已在 `main.py` 顶部导入（`_source_records` 用到 `asyncio.sleep`）；若没有就补上。

- [ ] **Step 4: 运行集成检查确认通过**

Run: `/Users/coe/project/AstrBot/.venv/bin/python tests/integration_check.py`
Expected: 全部通过，且新增的 15 条断言均 PASS

- [ ] **Step 5: 跑全量测试**

Run: `/Users/coe/project/AstrBot/.venv/bin/python -m pytest tests -q && /Users/coe/project/AstrBot/.venv/bin/python tests/integration_check.py`
Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
git add main.py tests/integration_check.py
git commit -m "feat: prefer the self-hosted source and degrade to the website"
```

---

## Task 11: 排除过滤接入推送

**Files:**
- Modify: `main.py`（`_announce_poll_job` 的 `fresh` 计算处）
- Modify: `tests/integration_check.py`

**Interfaces:**
- Consumes: `_is_excluded`（Task 10）
- Produces: 被排除的条目既不推送也不推进水位线

- [ ] **Step 1: 写失败的断言**

追加到 `tests/integration_check.py`，紧接 10 那段之后。**必须自己构造插件并显式配置关键词**——10 最后留下的那个 `plugin` 配的是 `{"feed_source": "official"}`，没设 `feed_exclude_keywords`，空关键词等于什么都不过滤。

```python
    # ── 排除过滤：命中关键词的条目既不推送，也不推进水位线 ────────────────
    FILTER_TS = int(time.time())

    def filter_fixture(ident, title, ts):
        return {
            "id": ident,
            "title": title,
            "author": "明日方舟",
            "brief": "",
            "group": "OFFICIAL",
            "group_cn": "官方",
            "url": "",
            "ts": ts,
            "date_text": "2026-10-12 11:00",
        }

    filter_records = [
        filter_fixture("1", "【签到福利】森空岛10月签到福利活动开启！", FILTER_TS - 60),
        filter_fixture("2", "《明日方舟》EP - 大地之盐", FILTER_TS - 30),
        filter_fixture("3", "【有奖活动】猜猜我是谁#2全新谜题开启！", FILTER_TS - 20),
    ]

    filtering = plugin_module.ArknightsPlugin(
        context=SimpleNamespace(send_message=None),
        config={"feed_exclude_keywords": "签到福利,有奖活动,模组"},
    )
    kept = filtering._filter_pushable(
        filter_records, watermark=FILTER_TS - 120, now=FILTER_TS, window=86400
    )
    check("排除关键词被过滤", [item["id"] for item in kept] == ["2"], kept)
    check(
        "未命中关键词的条目不误伤",
        filtering._is_excluded("《明日方舟》EP - 大地之盐") is False,
        None,
    )

    # 关键词留空时必须全部放行，否则用户没法关掉过滤
    permissive = plugin_module.ArknightsPlugin(
        context=SimpleNamespace(send_message=None), config={"feed_exclude_keywords": ""}
    )
    all_kept = permissive._filter_pushable(
        filter_records, watermark=FILTER_TS - 120, now=FILTER_TS, window=86400
    )
    check("关键词留空时不过滤", len(all_kept) == 3, all_kept)

    # 时间窗口依旧生效：把「现在」推到 48 小时后，三条都过期
    expired = filtering._filter_pushable(
        filter_records,
        watermark=FILTER_TS - 120,
        now=FILTER_TS + 48 * 3600,
        window=86400,
    )
    check("超出时间窗口的条目不会被推送", expired == [], expired)
```

- [ ] **Step 2: 运行确认失败**

Run: `/Users/coe/project/AstrBot/.venv/bin/python tests/integration_check.py`
Expected: FAIL — `AttributeError: 'ArknightsPlugin' object has no attribute '_filter_pushable'`

- [ ] **Step 3: 提取推送筛选方法并接线**

在 `main.py` 新增（放在 `_is_excluded` 之后）：

```python
    def _filter_pushable(
        self,
        records: list[dict[str, Any]],
        watermark: int,
        now: float,
        window: int,
    ) -> list[dict[str, Any]]:
        """Select the records worth pushing.

        A record qualifies when it is newer than the watermark, falls inside the
        age window, and is not excluded by keyword. Filtering happens here rather
        than at the source so both sources behave identically.

        Args:
            records: Candidate records, newest first.
            watermark: Newest timestamp already pushed.
            now: Current unix time.
            window: Maximum age in seconds.

        Returns:
            The records to push, newest first.
        """
        return [
            item
            for item in records
            if int(item["ts"]) > watermark
            and 0 < now - int(item["ts"]) <= window
            and not self._is_excluded(str(item.get("title") or ""))
        ]
```

在 `_announce_poll_job` 中把原来的列表推导替换为：

```python
        fresh = self._filter_pushable(records, watermark, now, window)
```

- [ ] **Step 4: 运行集成检查确认通过**

Run: `/Users/coe/project/AstrBot/.venv/bin/python tests/integration_check.py`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add main.py tests/integration_check.py
git commit -m "feat: honour the exclusion keywords when pushing"
```

---

## Task 12: 版本、文档与发布

**Files:**
- Modify: `metadata.yaml`、`main.py`（`PLUGIN_VERSION`）、`README.md`
- Modify: `docs/preview/`（若新增预览图）

**Interfaces:**
- Consumes: 全部前置任务
- Produces: `0.4.0` 版本四处一致

- [ ] **Step 1: 四处版本一起改**

- `metadata.yaml`：`version: "0.4.0"`；`desc` 补一句「官方动态含 PV/EP 视频」
- `main.py`：`PLUGIN_VERSION = "0.4.0"`
- `README.md`：版本徽章改为 `0.4.0`
- `README.md`：新增更新日志标题 `### 0.4.0 (2026-10-12)`

- [ ] **Step 2: README 补配置说明与更新日志**

在配置表格中加入新键（沿用表格既有列），并在更新日志写入：

```markdown
### 0.4.0 (2026-10-12)

- 公告推送默认改用自建的森空岛「官方」栏目源，内容比官网公告更全：新增官方
  PV / EP、干员展示、服饰、家具、OST 等官网不发布的动态。
- 视频类动态以封面图 + 标题 + 正文摘要推送，不下载视频文件、不附原文链接。
- 自建源在配置的时间窗口内失败达到阈值时，会向订阅者告警并自动降级到官网
  公告源；恢复后自动切回并再次通知。
- 新增公告推送排除关键词，默认排除签到福利、周记表、每日谜题、创作集锦、
  模组/工具更新、有奖活动等社区向内容。
- 自建源可自行部署，见 `server/README.md`。
```

- [ ] **Step 3: 跑全部测试与格式检查**

Run:
```bash
/Users/coe/project/AstrBot/.venv/bin/python -m pytest tests -q
/Users/coe/project/AstrBot/.venv/bin/python tests/integration_check.py
/Users/coe/project/AstrBot/.venv/bin/ruff format . && /Users/coe/project/AstrBot/.venv/bin/ruff check .
```
Expected: 测试全 PASS；ruff 无告警

- [ ] **Step 4: 渲染预览图并同步到 docs/preview**

（仅在新增或改动卡片模板时执行；本计划复用 `announce_detail.html`，若渲染结果无变化则跳过）

Run: `/Users/coe/project/AstrBot/.venv/bin/python tests/render_preview.py`
Expected: 输出写入 `docs/preview/`

- [ ] **Step 5: 提交并推送**

```bash
git add -A
git commit -m "chore: release 0.4.0 with the self-hosted official feed"
git push origin main
```

（GitHub 推送偶发 LibreSSL / HTTP2 报错，失败时重试并用 `git ls-remote` 确认。）

- [ ] **Step 6: 部署到宁波节点并验证**

```bash
ssh yuyu 'cd /root/data/plugins/astrbot_plugin_arknights && git pull --ff-only'
ssh yuyu 'systemctl restart astrbot && sleep 25 && systemctl is-active astrbot'
ssh yuyu 'grep -E "公告轮询|自建源|降级" /root/data/logs/astrbot.log | tail -20'
```

Expected: `active`；日志出现自建源取数成功（首次轮询会初始化水位线，不推送）。随后在群 `454206542` 用 `~ark订阅公告` 验证一条真实推送。

---

## 自检记录

**1. 规格覆盖**

| 需求 | 对应任务 |
|:--|:--|
| 自建源、使用者零凭据 | 1–6（服务端持有凭证）、7/9（插件只配 URL + Key） |
| Key 内置在插件中 | 9（`feed_api_key` 默认值即服务端 key） |
| 默认自建源、降级官网源 | 9（`feed_source` 默认 `selfhosted`）、10（重试与降级状态机） |
| 只保留官方栏目 | 2（`cateId=1`） |
| 排除签到福利/森空岛活动/模组工具 | 9（关键词默认值）、11（过滤接线） |
| 视频轻量推送、无原文链接 | 7（`body_html` = 正文 + 封面图，不含链接）、10/11 未在文案中附加 URL |
| 轮询失败 → 重试 → 全失败才降级，并通知 | 10（`_feed_retry_delays` + `_source_records` + `_notify_feed_subscribers`） |
| 用户可配置 | 9（`feed_source` / `feed_retry_delays` / `feed_exclude_keywords` / 源地址与 Key） |
| 服务部署在 HK，子域 `ark.youyou.ink` | 6（子域站点块 + A 记录前置检查） |

**2. 占位符扫描**：无 TBD/TODO。唯一的运行期填值点是 Task 6 Step 4 生成的 API key，它在 Task 9 Step 1 被显式要求替换，并在 Task 9 Step 2 用断言校验（须以十六进制字符开头）。

**3. 类型一致性**：`FeedCache.snapshot()` 的键 `items`/`last_success_at`/`last_error`/`stale` 在 3 定义、4 消费、7 读取一致；`FeedClient.fetch()` 产出的记录键与 `core.announce.AnnounceClient.fetch()` 保持一致，`_announce_poll_job` 因此无需按源分支；`Store.feed_state()` 返回的 `active`（`""` = 正常、`"official"` = 已降级）在 8 定义、10 消费一致；`_is_excluded` 在 10 定义、11 复用；`FeedError` 在 7 定义、10 捕获。

**4. 待确认项（实现前需你拍板）**

- **服务端凭证来源**：需要一个森空岛账号扫码（建议用一个专用小号，而不是你的主号或任何插件用户已绑定的号）。

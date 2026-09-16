# 罗德岛终端（astrbot_plugin_arknights）P0–P2 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付一个可安装运行的明日方舟 AstrBot 插件，实现账号绑定、便签/理智/签到、干员列表与干员面板，全部输出为图片卡片。

**Architecture:** 直连鹰角/森空岛官方接口，不依赖第三方服务。`core/` 下的模块全部不导入 `astrbot`，因此可用纯 pytest 单测；`main.py` 只做指令路由、定时任务与消息收发。渲染走自建 Playwright + Jinja2（AstrBot 内置 `html_render` 只支持远端 t2i，无法自定义模板本地渲染）。

**Tech Stack:** Python 3.12、httpx、pycryptodome、qrcode、jinja2、playwright、apscheduler、pytest + anyio

**Spec:** `docs/specs/2026-09-16-arknights-plugin-design.md`

## Global Constraints

- **许可证：MIT。** 不得复制 AGPL-3.0 项目的代码。已确认 **`astrbot_plugin_endfield` 与 `astrbot_plugin_mrfz_haunting_query` 均为 AGPL-3.0**，**`astrbot_plugin_maa` 亦为 AGPL-3.0**。渲染器必须独立实现，不得移植 `endfield/core/render.py`。`astrbot_plugin_skland`（MIT）与 `AstrBot-SenKongDao-Check-in`（MIT）可作为算法参考，但协议常量与代码仍需自行实现并在 README 鸣谢。
- **`core/` 下任何模块都不得 `import astrbot`**（`store.py` 的默认路径解析除外，且必须延迟到函数内执行）。这是保证单测可运行的前提。
- 用户可见文案用中文；代码注释与 docstring 用英文，docstring 用 Google 风格（`Args:` / `Returns:` / `Raises:`）。
- 路径一律用 `pathlib.Path`，不用字符串拼接。
- 提交信息用 conventional commits（`feat:` / `fix:` / `test:` / `docs:` / `chore:`）。
- 每个 Task 结束前必须运行 `ruff format .` 与 `ruff check .` 且无错误。
- 测试命令中的 `$PY` 一律指 `/Users/coe/project/AstrBot/.venv/bin/python`。
- 异步测试用 `anyio`（已随环境提供），**不引入 pytest-asyncio**；根 `conftest.py` 提供 `anyio_backend` fixture 固定为 `asyncio`（否则 anyio 会尝试 trio）。
- 森空岛 AP 恢复速率固定 **360 秒/点**。

## 计划期的设计修正（相对 spec 的简化）

spec 的里程碑表把 `gamedata.py`（静态游戏表下载）列入 P2。计划期发现 **P2 不需要它**：

- `player/info` 已返回 `charInfoMap`（中文名 / 稀有度 / 职业），干员列表与面板的名称、星级、职业可直接取自接口。
- 模组名称由 `player/info` 的 `equipmentInfoMap` 提供。
- 技能用 `torappu.prts.wiki/assets/skill_icon/skill_icon_{skillId}.png` 图标 + 专精等级展示，无需技能名。
- 静态表下载（`character_table.json` 等）推迟到 **P3 抽卡分析**（那时才需要卡池与稀有度映射）。

因此 **`gamedata.py` 不列入 P0–P2**，`skills` 只展示图标与专精等级。

## File Structure

```
astrbot_plugin_arknights/
├── metadata.yaml            # 插件元数据
├── _conf_schema.json        # WebUI 配置 schema
├── requirements.txt         # 运行期依赖
├── LICENSE                  # MIT
├── README.md                # 安装、绑定、指令、鸣谢
├── main.py                  # 指令路由 + 定时任务 + 消息收发（唯一导入 astrbot 的文件）
├── core/
│   ├── __init__.py
│   ├── store.py             # 绑定与订阅持久化（原子写、0600）
│   ├── skland.py            # 森空岛：设备指纹、签名、OAuth、绑定、签到、player/info、理智外推
│   ├── hypergryph.py        # 鹰角账号：扫码登录、验证码登录、token 校验
│   ├── assets.py            # torappu 资源 URL 组装（纯函数）
│   └── render.py            # Playwright + Jinja2 渲染（独立实现）
├── templates/               # note.html / sanity.html / operator.html / operator_list.html / help.html / base.css
├── tests/
│   ├── conftest.py
│   ├── test_store.py
│   ├── test_skland_pure.py
│   ├── test_skland_client.py
│   ├── test_hypergryph.py
│   ├── test_assets.py
│   └── test_operators.py
└── docs/specs/2026-09-16-arknights-plugin-design.md
```

---

### Task 1: 插件骨架与配置

**Files:**
- Create: `metadata.yaml`, `_conf_schema.json`, `requirements.txt`, `LICENSE`, `README.md`, `core/__init__.py`, `tests/conftest.py`

**Interfaces:**
- Consumes: 无
- Produces: 插件目录名 `astrbot_plugin_arknights`（供 Task 6 的 `plugin_id` 使用）；配置项 `render_timeout`(int)、`sign_time`(string "HH:MM")、`sanity_poll_interval`(int)、`data_ttl`(int)、`max_bindings`(int)

- [ ] **Step 1: 创建 `metadata.yaml`**

```yaml
name: astrbot_plugin_arknights
display_name: 罗德岛终端
desc: 基于森空岛官方接口的明日方舟插件，支持账号绑定、便签、理智、签到与干员查询。
short_desc: 明日方舟数据查询与签到
version: "0.1.0"
author: coe
repo: https://github.com/coe/astrbot_plugin_arknights
astrbot_version: ">=4.16,<5"
```

- [ ] **Step 2: 创建 `_conf_schema.json`**

```json
{
  "render_timeout": {
    "description": "图片渲染超时时间(ms)",
    "type": "int",
    "default": 30000
  },
  "data_ttl": {
    "description": "玩家数据缓存时间(秒)",
    "type": "int",
    "default": 300,
    "hint": "同一账号重复查询在该时间内直接复用缓存，避免频繁请求触发风控"
  },
  "sign_time": {
    "description": "每日自动签到时间",
    "type": "string",
    "default": "00:05",
    "hint": "格式 HH:MM"
  },
  "sanity_poll_interval": {
    "description": "理智订阅轮询间隔(分钟)",
    "type": "int",
    "default": 20,
    "hint": "建议 10-30，过短可能触发风控"
  },
  "max_bindings": {
    "description": "单用户最大绑定数",
    "type": "int",
    "default": 5,
    "hint": "0 表示不限制"
  }
}
```

- [ ] **Step 3: 创建 `requirements.txt` 与 `core/__init__.py`**

`requirements.txt`:
```
httpx>=0.25.0
pycryptodome>=3.19.0
qrcode>=7.4
jinja2>=3.0
playwright>=1.40
apscheduler>=3.10.0
```

`core/__init__.py` 内容为空文件。

- [ ] **Step 4: 创建 `LICENSE`（MIT）与 `README.md` 骨架**

`LICENSE` 使用标准 MIT 全文，年份 2026，版权人 `coe`。

`README.md` 至少包含：项目简介、安装（含 `playwright install chromium`）、获取 token 的方法、指令表、鸣谢（`astrbot_plugin_skland`、`AstrBot-SenKongDao-Check-in`、`astrbot_plugin_endfield`）、MIT 许可声明。

- [ ] **Step 5: 创建 `tests/conftest.py`**

```python
import pytest


@pytest.fixture
def anyio_backend():
    """Force anyio's pytest plugin to run async tests on asyncio only."""
    return "asyncio"
```

- [ ] **Step 6: 验证配置可被解析**

Run:
```bash
cd /Users/coe/project/astrbot_plugin_arknights
$PY -c "import json,yaml;json.load(open('_conf_schema.json'));print(yaml.safe_load(open('metadata.yaml')))"
$PY -m pytest tests/ -v
```
Expected: 打印出 metadata 字典；pytest 报 `no tests ran`（退出码 5 可接受），且**不报导入错误**。

- [ ] **Step 7: 提交**

```bash
git add -A && git commit -m "feat: scaffold astrbot_plugin_arknights plugin"
```

---

### Task 2: 持久化层 `core/store.py`

**Files:**
- Create: `core/store.py`, `tests/test_store.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `Store(path: Path | None = None)`；`path=None` 时延迟解析为 `get_astrbot_plugin_data_path()/"astrbot_plugin_arknights"/"users.json"`
  - `async Store.get_user(user_key: str) -> dict | None`
  - `async Store.upsert_auth(user_key: str, token: str, skland_nickname: str, bindings: list[dict]) -> None`
  - `async Store.set_primary(user_key: str, uid: str) -> bool`
  - `async Store.delete_binding(user_key: str, uid: str) -> bool`
  - `async Store.remove_user(user_key: str) -> bool`
  - `async Store.list_sanity_subs() -> list[str]` / `async Store.set_sanity_sub(user_key: str, enabled: bool) -> None`
  - `async Store.list_sign_groups() -> list[str]` / `async Store.set_sign_group(group_id: str, enabled: bool) -> None`
  - 存储结构：`{"users": {user_key: {token, skland_nickname, bindings, primary_uid, created_at}}, "subs": {"sanity": [], "sign_groups": []}}`

- [ ] **Step 1: 写失败测试 `tests/test_store.py`**

```python
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
async def test_sanity_subscription_toggle(tmp_path):
    store = Store(tmp_path / "users.json")
    await store.set_sanity_sub("u1", True)
    assert await store.list_sanity_subs() == ["u1"]
    await store.set_sanity_sub("u1", True)
    assert await store.list_sanity_subs() == ["u1"]
    await store.set_sanity_sub("u1", False)
    assert await store.list_sanity_subs() == []


@pytest.mark.anyio
async def test_sign_group_toggle(tmp_path):
    store = Store(tmp_path / "users.json")
    await store.set_sign_group("g1", True)
    assert await store.list_sign_groups() == ["g1"]
    await store.set_sign_group("g1", False)
    assert await store.list_sign_groups() == []


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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/coe/project/astrbot_plugin_arknights && $PY -m pytest tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.store'`

- [ ] **Step 3: 实现 `core/store.py`**

关键实现要点（必须全部满足）：

- `_default_path()` 内部才 `from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path`，保证测试不需要 astrbot。
- 读：文件不存在或 JSON 解析失败 → 返回 `{"users": {}, "subs": {"sanity": [], "sign_groups": []}}`。
- 写：先写 `path.with_suffix(".tmp")`，`os.chmod(tmp, 0o600)`，再 `os.replace(tmp, path)`；`mkdir(parents=True, exist_ok=True)`。
- 所有异步方法用 `asyncio.Lock` 串行化，且每次操作前重新从磁盘读取，避免多实例数据竞争。
- `upsert_auth` 把 `bindings[0]["uid"]` 设为默认 `primary_uid`；`created_at` 用 `int(time.time())`。
- `delete_binding` 删除后若列表为空则移除该用户并返回 `True`；若删除的是 `primary_uid` 则把新的第一项设为 primary；uid 不存在返回 `False`。

- [ ] **Step 4: 运行测试确认通过**

Run: `$PY -m pytest tests/test_store.py -v`
Expected: 8 passed

- [ ] **Step 5: 格式化与提交**

```bash
.venv-agnostic: /Users/coe/project/AstrBot/.venv/bin/ruff format . && /Users/coe/project/AstrBot/.venv/bin/ruff check .
git add -A && git commit -m "feat: add binding and subscription persistence layer"
```

---

### Task 3: 森空岛签名与纯函数 `core/skland.py`（第一部分）

**Files:**
- Create: `core/skland.py`, `tests/test_skland_pure.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - 常量 `USER_AGENT: str`、`DES_RULE: dict`、`DES_TARGET: dict`、`BROWSER_ENV: dict`、`RSA_PUBLIC_KEY: str`
  - `des_encrypt(key: bytes, data: bytes) -> bytes`
  - `apply_des_rules(data: dict) -> dict`
  - `get_tn(data: dict) -> str`
  - `aes_encrypt(data: bytes, key: bytes) -> str`
  - `get_smid(now: datetime | None = None, uid: str | None = None) -> str`
  - `generate_signature(token: str, path: str, body_or_query: str, did: str, timestamp: int) -> tuple[str, dict]`
  - `derive_sanity(raw_current, max_ap, recovery_ts, seconds_per_point: int = 360, now: float | None = None) -> int`
  - `class Credential`（`token: str`、`cred: str`）、`class UserBinding`（`uid`、`game_id`、`nickname`、`channel_name`）、`class SignInResult`（`success`、`nickname`、`awards: list[str]`、`error: str`）

- [ ] **Step 1: 写失败测试 `tests/test_skland_pure.py`**

```python
import hashlib
import hmac
import json

from core.skland import derive_sanity, generate_signature, get_tn


def test_get_tn_sorts_keys_and_scales_ints():
    # ints are multiplied by 10000, nested dicts are recursed, falsy values skipped
    assert get_tn({"b": 1, "a": "x"}) == "x10000"
    assert get_tn({"a": "", "b": 2}) == "20000"
    assert get_tn({"a": {"y": 1, "x": 2}}) == "2000010000"


def test_generate_signature_is_deterministic():
    sign, header = generate_signature("tok", "/api/x", "a=1", "did123", 1700000000)
    expected_raw = f"/api/xa=11700000000{json.dumps(header, separators=(',', ':'))}"
    expected = hashlib.md5(
        hmac.new(b"tok", expected_raw.encode(), hashlib.sha256).hexdigest().encode()
    ).hexdigest()
    assert sign == expected
    assert header["dId"] == "did123"
    assert header["platform"] == "3"
    assert header["timestamp"] == "1700000000"


def test_derive_sanity_recovers_from_complete_recovery_time():
    now = 1_000_000.0
    # 3600s left => 10 points missing from max
    assert derive_sanity(0, 120, int(now + 3600), 360, now) == 110
    assert derive_sanity(5, 120, int(now + 360), 360, now) == 119


def test_derive_sanity_clamps_low():
    now = 1_000_000.0
    # more than max points of recovery left => clamp to 0
    assert derive_sanity(0, 10, int(now + 999_999), 360, now) == 0


def test_derive_sanity_full_when_no_countdown():
    now = 1_000_000.0
    assert derive_sanity(88, 120, -1, 360, now) == 120
    assert derive_sanity(500, 127, -1, 360, now) == 500


def test_derive_sanity_past_timestamp_treated_as_full():
    now = 1_000_000.0
    assert derive_sanity(30, 135, int(now - 60), 360, now) == 135


def test_derive_sanity_handles_missing_max():
    assert derive_sanity(None, None, None, 360, 1_000_000.0) == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `$PY -m pytest tests/test_skland_pure.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.skland'`

- [ ] **Step 3: 实现纯函数部分**

`DES_RULE` / `DES_TARGET` / `BROWSER_ENV` / `RSA_PUBLIC_KEY` 四个常量按森空岛协议填写（协议常量，字段与值见下）。函数签名语义：

- `des_encrypt(key, data)`：数据以 `\x00` 补齐到 8 字节倍数，密钥取前 8 字节并按 `\x00` 右补齐，`DES.MODE_ECB` 逐块加密。
- `apply_des_rules(data)`：对每个 key 查 `DES_RULE`；`is_encrypt == 1` 时用该条 `key` 做 `des_encrypt` 后 base64，输出到 `obfuscated_name`；否则原样输出到 `obfuscated_name`（无规则则保留原 key）。
- `get_tn(data)`：按键名升序；`int` 值乘 10000；`dict` 递归；其余值转字符串；**假值（空串/0/None）跳过**。
- `aes_encrypt(data, key)`：先 base64，再 `\x00` 补齐到 16 字节倍数，`AES.MODE_CBC` + IV `b"0102030405060708"`，`pad(..., 16)` 后返回 hex。
- `get_smid()`：`时间串 + md5(uuid) + "00"`，再取 `md5("smsk_web_" + v)` 前 7 字节 hex，拼成 `v + suffix + "0"`。
- `generate_signature`：`timestamp` 为**必填参数**（便于测试）；`header_ca = {"platform":"3","timestamp":str(timestamp),"dId":did,"vName":"1.0.0"}`；`s = path + body_or_query + str(timestamp) + json.dumps(header_ca, separators=(",",":"))`；`sign = md5(hmac_sha256(token, s).hexdigest())`。
- `derive_sanity`：`recovery_ts > now` 且 `max_ap > 0` → `max(0, min(max_ap - ceil((recovery_ts-now)/seconds_per_point), max_ap))`；否则 `max(raw_current, max_ap)`；所有输入 `None` 按 0 处理。

- [ ] **Step 4: 运行测试确认通过**

Run: `$PY -m pytest tests/test_skland_pure.py -v`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
ruff format . && ruff check .
git add -A && git commit -m "feat: add skland signature and sanity extrapolation helpers"
```

---

### Task 4: 森空岛客户端 `core/skland.py`（第二部分）

**Files:**
- Modify: `core/skland.py`
- Create: `tests/test_skland_client.py`

**Interfaces:**
- Consumes: Task 3 的全部纯函数与数据类
- Produces: `SklandClient`，方法：
  - `async get_device_id() -> str`（结果缓存在实例上）
  - `async get_authorization(user_token: str) -> str`
  - `async get_credential(authorization: str) -> Credential`
  - `async get_binding_list(cred: Credential) -> list[UserBinding]`
  - `async sign_arknights(cred: Credential, binding: UserBinding) -> SignInResult`
  - `async get_player_info(cred: Credential, uid: str) -> dict`
  - `async close() -> None`
  - `def parse_sanity(data: dict, now: float | None = None) -> dict`，返回 `{"current": int, "max": int, "complete_recovery_time": int}`
  - 构造参数：`SklandClient(base_url_overrides: dict | None = None)`，其中 override key 为 `"fp"` / `"as"` / `"zonai"`，用于测试时指向 mock server

- [ ] **Step 1: 写失败测试 `tests/test_skland_client.py`**

用 `httpx.MockTransport` 注入假响应，覆盖：正常绑定列表、`code != 0`、401、超时、畸形 JSON。

```python
import httpx
import pytest

from core.skland import SklandClient


def _client(handler):
    c = SklandClient()
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    c._did = "Btest"
    return c


@pytest.mark.anyio
async def test_get_binding_list_parses_arknights_only():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "list": [
                        {
                            "appCode": "arknights",
                            "bindingList": [
                                {
                                    "uid": "1",
                                    "nickName": "探姬#9315",
                                    "channelName": "官服",
                                    "channelMasterId": "1",
                                }
                            ],
                        },
                        {"appCode": "endfield", "bindingList": [{"uid": "9"}]},
                    ]
                },
            },
        )

    bindings = await _client(handler).get_binding_list(None)
    assert [b.uid for b in bindings] == ["1"]
    assert bindings[0].nickname == "探姬#9315"


@pytest.mark.anyio
async def test_business_error_raises():
    def handler(request):
        return httpx.Response(200, json={"code": 10001, "message": "用户未登录"})

    with pytest.raises(Exception, match="用户未登录"):
        await _client(handler).get_binding_list(None)


@pytest.mark.anyio
async def test_http_401_raises_auth_error():
    def handler(request):
        return httpx.Response(401, json={"message": "unauthorized"})

    with pytest.raises(Exception):
        await _client(handler).get_player_info(None, "1")


@pytest.mark.anyio
async def test_malformed_json_raises():
    def handler(request):
        return httpx.Response(200, text="<html>oops</html>")

    with pytest.raises(Exception):
        await _client(handler).get_player_info(None, "1")


@pytest.mark.anyio
async def test_transport_error_raises():
    def handler(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(Exception):
        await _client(handler).get_player_info(None, "1")


def test_parse_sanity_reads_status_ap():
    data = {"status": {"ap": {"current": 10, "max": 135, "completeRecoveryTime": -1}}}
    assert SklandClient.parse_sanity(data, now=1_000_000.0) == {
        "current": 135,
        "max": 135,
        "complete_recovery_time": -1,
    }
```

- [ ] **Step 2: 运行测试确认失败**

Run: `$PY -m pytest tests/test_skland_client.py -v`
Expected: FAIL — `ImportError: cannot import name 'SklandClient'`

- [ ] **Step 3: 实现 `SklandClient`**

要点：

- 默认地址常量 `FP_BASE = "https://fp-it.portal101.cn"`、`AS_BASE = "https://as.hypergryph.com"`、`ZONAI_BASE = "https://zonai.skland.com"`，构造时可按 override 替换。
- `_request(method, url, headers=None, json_data=None)`：单次请求；`raise_for_status()`；`resp.json()`；任何 `httpx.HTTPError` / `json.JSONDecodeError` → 抛 `SklandError`（自定义异常，继承 `Exception`）。**不在客户端内部吞异常**，由调用方决定提示；这样测试才能断言。
- `get_device_id()`：按 Task 3 的流程构造指纹 POST `/deviceprofile/v4`，`code != 1100` 抛 `SklandError`，成功后前缀 `B`。
- 受签名请求统一走 `_signed_headers(url, method, body, cred)`，`timestamp = int(time.time()) - 2`。
- `get_binding_list` 只保留 `appCode == "arknights"`，`UserBinding.game_id` 取 `channelMasterId`（缺省 `"1"`）。
- `sign_arknights`：当 `code != 0` 时返回 `SignInResult(success=False, error=message)` 而**不抛异常**（"已签到"属于正常业务结果）。
- `parse_sanity` 为 `@staticmethod`，从 `data["status"]["ap"]` 取值并调用 `derive_sanity(..., seconds_per_point=360, now=now)`。

- [ ] **Step 4: 运行测试确认通过**

Run: `$PY -m pytest tests/test_skland_client.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
ruff format . && ruff check .
git add -A && git commit -m "feat: add skland client for bindings, sign-in and player info"
```

---

### Task 5: 鹰角登录 `core/hypergryph.py`

**Files:**
- Create: `core/hypergryph.py`, `tests/test_hypergryph.py`

**Interfaces:**
- Consumes: 无（独立于 `skland.py`）
- Produces: `HypergryphClient`，方法：
  - `async create_qr() -> dict`，返回 `{"scan_id": str, "scan_url": str}`
  - `async poll_qr(scan_id: str) -> str | None`，未扫码返回 `None`，已扫码返回 `scan_code`
  - `async get_token_by_scan_code(scan_code: str) -> str`
  - `async send_phone_code(phone: str) -> None`
  - `async login_by_phone_code(phone: str, code: str) -> str`（返回鹰角 token）
  - `async verify_token(token: str) -> dict`（返回 `hgId`/`phone` 等基本信息，用于 token 绑定前的校验）
  - `async close() -> None`
  - 构造参数 `HypergryphClient(base_url: str = "https://as.hypergryph.com")`

- [ ] **Step 1: 写失败测试 `tests/test_hypergryph.py`**

```python
import httpx
import pytest

from core.hypergryph import HypergryphClient


def _client(handler):
    c = HypergryphClient()
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return c


@pytest.mark.anyio
async def test_create_qr_returns_scan_id_and_url():
    def handler(request):
        assert request.url.path == "/general/v1/gen_scan/login"
        return httpx.Response(
            200,
            json={
                "status": 0,
                "data": {
                    "scanId": "abc",
                    "scanUrl": "hypergryph://scan_login?scanId=abc",
                },
            },
        )

    qr = await _client(handler).create_qr()
    assert qr["scan_id"] == "abc"
    assert qr["scan_url"].startswith("hypergryph://")


@pytest.mark.anyio
async def test_poll_qr_pending_returns_none():
    def handler(request):
        return httpx.Response(200, json={"status": 100, "msg": "未扫码"})

    assert await _client(handler).poll_qr("abc") is None


@pytest.mark.anyio
async def test_poll_qr_scanned_returns_code():
    def handler(request):
        return httpx.Response(200, json={"status": 0, "data": {"scanCode": "sc1"}})

    assert await _client(handler).poll_qr("abc") == "sc1"


@pytest.mark.anyio
async def test_login_by_phone_code_returns_token():
    def handler(request):
        return httpx.Response(200, json={"status": 0, "data": {"token": "T1"}})

    assert await _client(handler).login_by_phone_code("138", "123456") == "T1"


@pytest.mark.anyio
async def test_send_phone_code_raises_on_business_error():
    def handler(request):
        return httpx.Response(200, json={"status": 1, "msg": "手机号格式错误"})

    with pytest.raises(Exception, match="手机号格式错误"):
        await _client(handler).send_phone_code("bad")


@pytest.mark.anyio
async def test_verify_token_returns_basic_info():
    def handler(request):
        assert request.url.params["token"] == "T1"
        return httpx.Response(200, json={"status": 0, "data": {"hgId": "123"}})

    assert (await _client(handler).verify_token("T1"))["hgId"] == "123"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `$PY -m pytest tests/test_hypergryph.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.hypergryph'`

- [ ] **Step 3: 实现 `HypergryphClient`**

要点：

- 扫码固定 `appCode = "4ca99fa6b56cc2ba"`（森空岛）。实测该 appCode 使 `enableScanAppList` 只含森空岛，且与后续 `oauth2/grant` 一致。
- `poll_qr` 用 **GET** `/general/v1/scan_status?scanId=`；`status == 100`（未扫码）→ `None`；`status == 0` → `data["scanCode"]`；其他 status → 抛 `HypergryphError(msg)`。
- `send_phone_code` 用 `POST /general/v1/send_phone_code`，body `{"phone": phone, "type": 2}`。
- `login_by_phone_code` 用 `POST /user/auth/v2/token_by_phone_code`，body `{"phone": phone, "code": code}`，返回 `data["token"]`。
- `verify_token` 用 `GET /user/info/v1/basic?token=`，返回 `data`。
- 统一 `_request` 语义同 Task 4：`status != 0` 抛 `HypergryphError(msg)`。

- [ ] **Step 4: 运行测试确认通过**

Run: `$PY -m pytest tests/test_hypergryph.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
ruff format . && ruff check .
git add -A && git commit -m "feat: add hypergryph qr and sms login client"
```

---

### Task 6: `main.py` 账号指令与帮助菜单

**Files:**
- Create: `main.py`
- Modify: `README.md`（补指令表）

**Interfaces:**
- Consumes: `Store`（Task 2）、`SklandClient`（Task 4）、`HypergryphClient`（Task 5）
- Produces: 插件类 `ArknightsPlugin(Star)`；内部辅助 `async def _resolve_binding(event) -> tuple[dict, dict] | None`（返回 `(user, binding)`），供 P1/P2 的所有查询指令复用

- [ ] **Step 1: 实现插件类与生命周期**

要点：

- `@register("astrbot_plugin_arknights", "coe", "罗德岛终端", "0.1.0")`。
- `__init__`：构造 `Store()`、`SklandClient()`、`HypergryphClient()`，读配置项到实例属性。
- `initialize()`：启动 apscheduler（P1 使用，Task 10 再填任务）。
- `terminate()`：关闭两个 client、shutdown scheduler、关闭渲染器。
- `_resolve_binding`：取 `event.get_sender_id()`；无绑定返回 `None` 并由调用方提示「请先私聊发送 `扫码绑定`」；有绑定时用 `primary_uid` 定位 binding。

- [ ] **Step 2: 实现三种绑定指令**

- `@filter.command("token绑定")`：参数为 token；调用 `skland.get_authorization` → `get_credential` → `get_binding_list` 完成真实校验；无方舟角色则提示；成功写库。**仅私聊**（`event.is_private_chat()` 为假时拒绝）。
- `@filter.command("验证码绑定")`：一个参数时视为手机号 → `send_phone_code`；两个参数时视为手机号+验证码 → `login_by_phone_code` 拿 token，再走与 token 绑定相同的落库流程。
- `@filter.command("扫码绑定")`：`create_qr` → 用 `qrcode` 生成 PNG（`hypergryph://` 是自定义协议，**不能发链接**）→ 发图片 → 后台任务轮询 `poll_qr`（间隔 2 秒，上限 120 秒）→ 成功则落库并**撤回二维码消息**；超时/失败同样撤回并提示。

- [ ] **Step 3: 实现账号管理指令**

- `@filter.command("绑定列表")`：输出每个绑定的序号、昵称、服务器、uid 尾号，标注当前主账号；**不回显 token**。
- `@filter.command("切换绑定")`：参数为序号 → `set_primary`。
- `@filter.command("删除绑定")`：参数为序号 → `delete_binding`。
- `@filter.command("ark")`：帮助菜单图片（Task 7 完成后接入渲染，本 Task 先输出文本版帮助，Task 7 再替换为图片）。

- [ ] **Step 4: 手工验证（需要真实账号）**

至少验证：`token绑定` 用真实 token 能成功并写入 `data/plugin_data/astrbot_plugin_arknights/users.json`（权限 600）；`绑定列表` 显示正确；群聊中发送绑定指令被拒绝。
无法实测扫码/验证码时，记录实际返回的错误信息，用于调整提示文案。

- [ ] **Step 5: 提交**

```bash
ruff format . && ruff check .
git add -A && git commit -m "feat: add account binding commands and help entry"
```

---

### Task 7: 渲染基座 `core/render.py` + `core/assets.py`

**Files:**
- Create: `core/render.py`, `core/assets.py`, `templates/base.css`, `templates/help.html`, `tests/test_assets.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `assets.char_avatar(char_id: str) -> str`、`assets.char_portrait(char_id: str, phase: int = 2) -> str`、`assets.skill_icon(skill_id: str) -> str`
  - `Renderer(templates_dir: Path, cache_dir: Path, timeout_ms: int = 30000)`；`async render_html(template_name: str, data: dict) -> Path | None`；`async close() -> None`

- [ ] **Step 1: 写失败测试 `tests/test_assets.py`**

```python
from core import assets


def test_char_avatar_url():
    assert assets.char_avatar("char_002_amiya") == (
        "https://torappu.prts.wiki/assets/char_avatar/char_002_amiya.png"
    )


def test_char_portrait_defaults_to_elite_two():
    assert assets.char_portrait("char_002_amiya").endswith(
        "/char_portrait/char_002_amiya_2.png"
    )
    assert assets.char_portrait("char_002_amiya", 1).endswith(
        "/char_portrait/char_002_amiya_1.png"
    )


def test_skill_icon_url():
    assert assets.skill_icon("skchr_amiya_3").endswith(
        "/skill_icon/skill_icon_skchr_amiya_3.png"
    )
```

- [ ] **Step 2: 运行测试确认失败**

Run: `$PY -m pytest tests/test_assets.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.assets'`

- [ ] **Step 3: 实现 `core/assets.py`**

三个纯函数，基址 `https://torappu.prts.wiki/assets`（已实测 200）。`skill_icon` 需处理 `skcom_` 前缀（通用技能）——先做 `skill_icon_{skill_id}.png`，与实测一致。

- [ ] **Step 4: 运行测试确认通过**

Run: `$PY -m pytest tests/test_assets.py -v`
Expected: 3 passed

- [ ] **Step 5: 实现 `core/render.py`（独立实现，不得参考 AGPL 代码）**

要点：

- `jinja2.Environment(loader=FileSystemLoader(templates_dir), autoescape=True)`。
- 渲染前把模板中 `__ASSET__/` 前缀引用的本地文件（CSS、字体、图片）替换为 data URI，避免 `file://` 依赖。
- Playwright 浏览器**实例内单例**，`asyncio.Lock` 保护 `start()`；`device_scale_factor=2`，viewport 宽 1000。
- 截图为 `locator("body > *").first` 的 bounding box，宽高各 +2px 后 `clip`；输出 JPEG quality 85 到 `cache_dir/render_<uuid8>.jpg`。
- 任何异常 → 记日志并返回 `None`（调用方降级为文本）。
- `close()` 关闭 browser 与 playwright。

- [ ] **Step 6: 渲染冒烟验证**

安装并写好 `templates/help.html` 后，用一个临时脚本渲染帮助页，人工确认出图非空白、中文正常、宽度合理。若 `playwright` 未安装则先执行：

```bash
/Users/coe/project/AstrBot/.venv/bin/pip install playwright
/Users/coe/project/AstrBot/.venv/bin/playwright install chromium
```

- [ ] **Step 7: 把 `ark` 帮助菜单切到图片渲染**

- [ ] **Step 8: 提交**

```bash
ruff format . && ruff check .
git add -A && git commit -m "feat: add playwright renderer and torappu asset urls"
```

---

### Task 8: 便签 `便签`

**Files:**
- Create: `templates/note.html`
- Modify: `main.py`

**Interfaces:**
- Consumes: `_resolve_binding`、`SklandClient.get_player_info`、`Renderer.render_html`、`assets.*`
- Produces: `def build_note_context(data: dict) -> dict`（放在 `main.py` 中，纯函数、便于手工核对）与 `@filter.command("便签")`

- [ ] **Step 1: 明确便签字段映射**

从 `player/info` 取值（实测确认存在）：

| 展示项 | 来源 |
|---|---|
| 昵称 / 等级 | `status.name` / `status.level` |
| 入职日期 | `status.registerTs`（时间戳 → `YYYY-MM-DD`） |
| 主线进度 | `status.mainStageProgress`（全通关时为空） |
| 干员数 / 皮肤数 | `status.charCnt` / `status.skinCnt`（实测该账号为 0，需与 `len(chars)`、`len(skins)` 取较大值兜底） |
| 助战三人 | `assistChars[].charId/level/evolvePhase/potentialRank/specializeLevel` |
| 理智 | `status.ap`，用 `parse_sanity` 外推 |
| 每日/每周任务 | `routine.daily.current/total`、`routine.weekly.current/total` |
| 剿灭合成玉 | `campaign.reward` |
| 数据时间 | `status.storeTs`（**必须显示**，接口返回的是上次同步快照） |

- [ ] **Step 2: 实现 `build_note_context` 与 `便签` 指令，写 `templates/note.html`**

`note.html` 要求：单列卡片、顶部博士名与等级、助战三人头像横排（`assets.char_avatar`）、理智进度条、任务进度、右下角数据时间。所有远程图片用 `loading="eager"` 以保证截图前加载完成。

- [ ] **Step 3: 验证**

真实账号执行 `便签`，人工检查：昵称/等级/助战/理智/数据时间正确；干员数与皮肤数非 0。

- [ ] **Step 4: 提交**

```bash
ruff format . && ruff check .
git add -A && git commit -m "feat: add player note card"
```

---

### Task 9: 理智 `理智` + 回满时间

**Files:**
- Create: `templates/sanity.html`
- Modify: `main.py`

**Interfaces:**
- Consumes: `SklandClient.parse_sanity`、`Renderer`
- Produces: `def format_remaining(seconds: int) -> str`（纯函数）与 `@filter.command("理智")`

- [ ] **Step 1: 写失败测试**

在 `tests/test_sanity_format.py` 中：

```python
from main import (
    format_remaining,
)  # 若 main 导入 astrbot 导致不可测，则把该函数放到 core/assets.py 同级的新模块


def test_format_remaining_hours_and_minutes():
    assert format_remaining(0) == "已回满"
    assert format_remaining(3600) == "1小时0分"
    assert format_remaining(3660) == "1小时1分"
    assert format_remaining(59) == "0分"
```

> 若 `from main import ...` 因导入 `astrbot` 失败，则把 `format_remaining` 放到 `core/skland.py` 并从那里导入。**不要**为了测试而给 `main.py` 加 `astrbot` 的桩。

- [ ] **Step 2: 运行测试确认失败**

Run: `$PY -m pytest tests/test_sanity_format.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: 实现 `format_remaining` 与 `理智` 指令 + `templates/sanity.html`**

卡片内容：当前/上限、外推后的当前值、距回满剩余时间（由 `completeRecoveryTime - now` 计算，`<= 0` 显示「已回满」）、数据时间、森空岛昵称。恢复速率说明「6 分钟/点」写在卡片角落。

- [ ] **Step 4: 运行测试确认通过并手工验证**

Run: `$PY -m pytest tests/test_sanity_format.py -v`
Expected: 4 passed
手工：真实账号 `理智` 出图正确；再用 Task 3 的边界用例人工核对外推值与游戏内数值一致（满值/未满各验一次）。

- [ ] **Step 5: 提交**

```bash
ruff format . && ruff check .
git add -A && git commit -m "feat: add sanity card with recovery extrapolation"
```

---

### Task 10: 签到 + 定时任务 + 订阅推送

**Files:**
- Modify: `main.py`、`core/store.py`（若订阅接口需微调）、`_conf_schema.json`（如需补充）

**Interfaces:**
- Consumes: `SklandClient.sign_arknights`、`Store` 订阅接口
- Produces:
  - `@filter.command("签到")`
  - `@filter.command("订阅理智")` / `@filter.command("取消订阅理智")`
  - `@filter.command("订阅签到")` / `@filter.command("取消订阅签到")`
  - `async def _auto_sign_job(self)`：遍历所有绑定账号逐个签到，账号间隔 3 秒随机抖动
  - `async def _sanity_poll_job(self)`：遍历理智订阅用户，外推后判断是否回满，回满则私聊推送

- [ ] **Step 1: 实现手动签到**

`签到`：调用 `sign_arknights`；`success=False` 且 message 含「已签到」类关键词时按「今日已签到」友好提示，其余错误原样提示。结果用文本输出（无需出图）。

- [ ] **Step 2: 写订阅存储的失败测试（若 Task 2 未覆盖）**

覆盖：`set_sanity_sub` 幂等、`list_sign_groups` 顺序稳定、订阅用户在 `remove_user` 后不再出现于订阅列表。

- [ ] **Step 3: 实现定时任务**

- apscheduler `AsyncIOScheduler`，`CronTrigger` 按 `sign_time` 每日执行 `_auto_sign_job`。
- `IntervalTrigger(minutes=sanity_poll_interval)` 执行 `_sanity_poll_job`，间隔下限钳制为 10 分钟。
- 每个账号之间 `await asyncio.sleep(3 + random.random()*3)` 做风控抖动。
- 推送目标：优先私聊；`订阅签到` 在群聊中使用时记录该群，签到时在群内 @ 触发者。
- 推送失败（如无可达会话）只记日志，不能让定时任务整体崩掉。

- [ ] **Step 4: 实现 `player/info` 的 TTL 缓存**

在插件实例上维护 `dict[uid -> (expire_ts, data)]`，`data_ttl` 秒内复用。`便签`、`理智`、`干员列表`、`干员面板` 共用同一缓存，避免同一用户连续查询打三次接口。

- [ ] **Step 5: 手工验证**

- `签到` 真实执行一次，确认返回奖励或「已签到」。
- 临时把 `sanity_poll_interval` 设为最小值并构造一个接近回满的账号，确认推送发生且不会重复推送（同一账号回满只推一次，直到理智被消耗）。
- 确认 `terminate()` 能干净关闭 scheduler（重载插件不报错、不残留任务）。

- [ ] **Step 6: 提交**

```bash
ruff format . && ruff check .
git add -A && git commit -m "feat: add sign-in, scheduler and subscription push"
```

---

### Task 11: 干员列表 `干员列表`

**Files:**
- Create: `templates/operator_list.html`, `tests/test_operators.py`
- Modify: `main.py`

**Interfaces:**
- Consumes: `player/info` 的 `chars` 与 `charInfoMap`
- Produces: `def group_operators(chars: list[dict], char_info: dict) -> list[dict]`（按职业分组、组内按稀有度降序）

- [ ] **Step 1: 写失败测试 `tests/test_operators.py`**

```python
from core.operators import PROFESSION_CN, group_operators


def test_profession_cn_covers_all_eight_professions():
    assert PROFESSION_CN["CASTER"] == "术师"
    assert len(PROFESSION_CN) == 8


def test_group_operators_groups_and_sorts():
    chars = [
        {"charId": "a", "level": 1, "evolvePhase": 0, "potentialRank": 0},
        {"charId": "b", "level": 1, "evolvePhase": 0, "potentialRank": 0},
        {"charId": "c", "level": 1, "evolvePhase": 0, "potentialRank": 0},
    ]
    info = {
        "a": {"name": "低星术师", "rarity": 0, "profession": "CASTER"},
        "b": {"name": "高星术师", "rarity": 5, "profession": "CASTER"},
        "c": {"name": "医疗", "rarity": 3, "profession": "MEDIC"},
    }
    groups = group_operators(chars, info)
    assert groups[0]["profession_cn"] == "术师"
    assert [o["name"] for o in groups[0]["operators"]] == ["高星术师", "低星术师"]
    # rarity from charInfoMap is zero-based, display stars = rarity + 1
    assert groups[0]["operators"][0]["stars"] == 6
    assert groups[1]["profession_cn"] == "医疗"


def test_group_operators_skips_unknown_and_orders_by_profession():
    chars = [{"charId": "x", "level": 1, "evolvePhase": 0, "potentialRank": 0}]
    groups = group_operators(chars, {})
    assert groups == []


def test_group_operators_includes_elite_and_level():
    chars = [{"charId": "a", "level": 90, "evolvePhase": 2, "potentialRank": 3}]
    info = {"a": {"name": "阿米娅", "rarity": 4, "profession": "CASTER"}}
    op = group_operators(chars, info)[0]["operators"][0]
    assert op["level"] == 90
    assert op["elite"] == 2
    assert op["potential"] == 3
    assert op["stars"] == 5
```

- [ ] **Step 2: 运行测试确认失败**

Run: `$PY -m pytest tests/test_operators.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.operators'`

- [ ] **Step 3: 实现 `core/operators.py`**

- `PROFESSION_CN`：`PIONEER→先锋`、`WARRIOR→近卫`、`SNIPER→狙击`、`CASTER→术师`、`MEDIC→医疗`、`SUPPORT→辅助`、`TANK→重装`、`SPECIAL→特种`（恰好 8 项）。
- 职业输出顺序固定按 `PROFESSION_CN` 的 8 个 key 遍历，保证渲染稳定。
- `group_operators` 忽略 `charInfoMap` 中查不到的 `charId`。

- [ ] **Step 4: 运行测试确认通过**

Run: `$PY -m pytest tests/test_operators.py -v`
Expected: 4 passed

- [ ] **Step 5: 实现 `干员列表` 指令 + `templates/operator_list.html`**

卡片：按职业分区，每区一行头像（`assets.char_avatar`），头像角标显示精英化阶段，右上角显示 `已持有 N / 总 M`（总数取 `len(char_info)`）。按稀有度降序排列。

- [ ] **Step 6: 手工验证并提交**

真实账号出图，核对干员总数与游戏内一致、头像无 404（`onerror` 时用占位图兜底）。

```bash
ruff format . && ruff check .
git add -A && git commit -m "feat: add operator roster card"
```

---

### Task 12: 干员面板 `<干员名>面板`

**Files:**
- Create: `templates/operator.html`
- Modify: `main.py`, `tests/test_operators.py`

**Interfaces:**
- Consumes: `group_operators` 所在模块、`player/info` 的 `chars`/`charInfoMap`/`equipmentInfoMap`、`assets.*`
- Produces: `def find_operator(chars: list[dict], char_info: dict, query: str) -> dict | None` 与 `@filter.regex(r"^\s*(.+?)\s*面板\s*$")`

- [ ] **Step 1: 写失败测试**

```python
def test_find_operator_by_exact_name():
    chars = [{"charId": "c1", "level": 90, "evolvePhase": 2, "skills": [], "equip": []}]
    info = {"c1": {"name": "阿米娅", "rarity": 4, "profession": "CASTER"}}
    assert find_operator(chars, info, "阿米娅")["char_id"] == "c1"


def test_find_operator_is_case_insensitive_for_latin_names():
    chars = [{"charId": "c1", "level": 1, "evolvePhase": 0, "skills": [], "equip": []}]
    info = {"c1": {"name": "Amiya", "rarity": 4, "profession": "CASTER"}}
    assert find_operator(chars, info, "amiya") is not None


def test_find_operator_missing_returns_none():
    assert find_operator([], {}, "不存在") is None


def test_find_operator_prefers_exact_over_substring():
    chars = [
        {"charId": "a", "level": 1, "evolvePhase": 0, "skills": [], "equip": []},
        {"charId": "b", "level": 1, "evolvePhase": 0, "skills": [], "equip": []},
    ]
    info = {
        "a": {"name": "阿米娅", "rarity": 4, "profession": "CASTER"},
        "b": {"name": "阿米娅·炎熔", "rarity": 5, "profession": "CASTER"},
    }
    assert find_operator(chars, info, "阿米娅")["char_id"] == "a"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `$PY -m pytest tests/test_operators.py -v -k find_operator`
Expected: FAIL — `ImportError: cannot import name 'find_operator'`

- [ ] **Step 3: 实现 `find_operator`**

匹配优先级：精确相等 → 去空格后相等 → 不区分大小写相等 → 子串包含。返回包含 `char_id`、`name`、`stars`、`level`、`elite`、`potential`、`favor`、`skills`、`equip` 的 dict。

- [ ] **Step 4: 运行测试确认通过**

Run: `$PY -m pytest tests/test_operators.py -v -k find_operator`
Expected: 4 passed

- [ ] **Step 5: 实现 `<干员名>面板` 指令 + `templates/operator.html`**

卡片：左半身立绘（`assets.char_portrait(char_id, 2)`，失败降级 `char_avatar`）、右侧等级/精英化/潜能/信赖条；技能区每行 `skill_icon(skill_id)` + 专精等级（`specializeLevel`）+ 主技能标记（`defaultSkillId`）；模组区列出 `equip` 的 `id`，名称从 `equipmentInfoMap` 取。

未找到干员时，回复「未找到干员 X，可用 `干员列表` 查看已持有干员」，**不要**出图。

- [ ] **Step 6: 手工验证并提交**

核对：立绘加载、技能专精等级与游戏一致、模组名称正确、重名干员按精确优先。

```bash
ruff format . && ruff check .
git add -A && git commit -m "feat: add operator detail card"
```

---

### Task 13: 集成验收

**Files:**
- Modify: `README.md`
- Create: 软链 `AstrBot/data/plugins/astrbot_plugin_arknights`

**Interfaces:**
- Consumes: 全部前置 Task
- Produces: 可加载运行的插件

- [ ] **Step 1: 创建软链并在 AstrBot 中加载**

```bash
ln -s /Users/coe/project/astrbot_plugin_arknights \
      /Users/coe/project/AstrBot/data/plugins/astrbot_plugin_arknights
```

启动 AstrBot，确认插件出现在插件列表、无导入错误、无依赖安装失败。检查日志中 `requirements.txt` 的自动安装是否成功（尤其 `playwright`）。

- [ ] **Step 2: 跑通端到端验收清单**

- [ ] `token绑定` 成功，`绑定列表` 正确，多账号可 `切换绑定`
- [ ] 群聊发送绑定指令被拒绝
- [ ] `便签` 出图，数据时间显示正确
- [ ] `理智` 出图，外推值与游戏内一致
- [ ] `签到` 返回正确结果
- [ ] `干员列表` 出图，总数与游戏内一致
- [ ] `<干员名>面板` 出图，技能/模组正确
- [ ] 重载插件不报错、不残留定时任务

- [ ] **Step 3: 全量检查**

```bash
cd /Users/coe/project/astrbot_plugin_arknights
/Users/coe/project/AstrBot/.venv/bin/ruff format .
/Users/coe/project/AstrBot/.venv/bin/ruff check .
$PY -m pytest tests/ -v
```
Expected: ruff 无告警；pytest 全绿。

- [ ] **Step 4: 完善 README 并提交**

README 需含：安装步骤（含 `playwright install chromium`）、三种绑定方式的获取 token 指引、完整指令表、FAQ（渲染失败/数据为快照/接口失效）、鸣谢与 MIT 声明、以及 §1.3 的自动化范围边界说明。

```bash
git add -A && git commit -m "docs: complete README and verify integration"
```

---

## Self-Review

**1. Spec 覆盖**

| Spec 要求 | 对应 Task |
|---|---|
| 森空岛签名 / dId / 绑定 / 签到 / player_info | 3, 4 |
| 扫码 + 验证码 + token 三种绑定 | 5, 6 |
| 多账号切换/删除、仅私聊、不回显 token | 6 |
| 原子写 + 0600 + `get_astrbot_plugin_data_path` | 2 |
| Playwright + Jinja2 渲染基座、降级文本 | 7 |
| torappu 资源 | 7 |
| 便签 | 8 |
| 理智外推 | 3（算法）, 9（展示） |
| 签到 + 定时 + 理智回满推送 + 群订阅 | 10 |
| 干员列表 | 11 |
| `<干员名>面板` | 12 |
| TTL 缓存 / 风控抖动 / 轮询下限 | 10 |
| 帮助菜单 | 6, 7 |
| 软链集成 + ruff + README | 13 |
| 里程碑中的 `gamedata.py` | **有意移出 P0–P2**，见「计划期的设计修正」，改由 P3 承担 |

**2. Placeholder 扫描**：无 TBD/TODO；所有测试步骤含可运行代码；模板未逐行给出但明确了字段映射与验收点（模板属设计产出，验收标准已量化）。

**3. 类型一致性**：`Store` 方法名在 Task 2 定义、Task 6/10 使用一致；`parse_sanity` 返回键 `current`/`max`/`complete_recovery_time` 在 Task 4 定义、Task 9 使用一致；`group_operators` 返回项的 `profession_cn`/`operators`/`stars`/`elite`/`potential` 在 Task 11 定义、`find_operator` 返回的 `char_id`/`stars`/`elite`/`potential`/`favor`/`skills`/`equip` 在 Task 12 使用一致。

**4. 未决事项**：Task 9 的 `format_remaining` 归属需在实现时按「core 不导入 astrbot」约束落到 `core/`；Task 4 的 `SklandError` 与 Task 5 的 `HypergryphError` 需在各自模块内定义。

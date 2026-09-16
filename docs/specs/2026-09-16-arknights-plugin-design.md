# 罗德岛终端 —— 明日方舟 AstrBot 插件设计文档

- 日期：2026-09-16
- 状态：待评审
- 目标仓库：`/Users/coe/project/astrbot_plugin_arknights`（软链至 `AstrBot/data/plugins/`）
- 对标产品：[astrbot_plugin_endfield](https://github.com/Entropy-Increase-Team/astrbot_plugin_endfield)（终末地协议终端）

---

## 1. 背景与目标

终末地插件通过第三方「协议终端」（`end-api.shallow.ink`）提供了账号绑定、便签、理智、干员面板、抽卡分析、自动签到、订阅提醒等一整套游戏助手能力。我们希望为明日方舟提供同等体验的插件。

**核心结论：明日方舟不需要第三方协议终端。** 森空岛官方接口 `GET /api/v1/game/player/info?uid=` 单次返回便签、理智、干员、基建、公招、剿灭、肉鸽、任务等全部展示数据。因此本插件直接对接鹰角/森空岛官方接口，不引入 `api_key` 与第三方可用性依赖。

### 1.1 v1 目标（P0–P2）

让用户完成「绑定账号 → 查看便签/理智 → 每日签到 → 查看干员」的完整闭环，并具备与终末地一致的图片卡片质量。

### 1.2 明确不在 v1 范围

抽卡记录/分析（P3）、基建/公招/剿灭/肉鸽（P4）、扫码以外的 WebUI 管理页、公告推送、日历、全服统计、抽卡模拟（P5）。架构需为其预留位置，但 v1 不实现。

---

## 2. 已确认的决策

| 决策项 | 结论 |
|---|---|
| v1 范围 | P0–P2：绑定 + 签到 + 便签 + 理智 + 干员 |
| 渲染方案 | 自带 Playwright + Jinja2（同终末地/sklandv2） |
| 项目落点 | `/Users/coe/project/astrbot_plugin_arknights` + 软链进 `data/plugins/` |
| 绑定方式 | 扫码登录 + 手机验证码，对标终末地插件 |

---

## 3. 技术可行性验证（实测证据，非推测）

| # | 验证项 | 证据 |
|---|---|---|
| 1 | 玩家全量数据 | 森空岛 `player/info` 返回 `status`(昵称/等级/注册日/主线进度/理智/助战)、`chars`(实测 153 个干员，含等级/精英化/潜能/技能专精/模组/信赖)、`charInfoMap`(中文名/稀有度/职业，**无需自建干员表**)、`building`、`recruit`、`campaign`、`rogue`、`routine` |
| 2 | 扫码登录链路 | 实测 `POST as.hypergryph.com/general/v1/gen_scan/login` → `{"scanId":..., "scanUrl":"hypergryph://scan_login?scanId=...", "enableScanAppList":[...]}`；`GET /general/v1/scan_status?scanId=` → 未扫码时 `{"msg":"未扫码","status":100}`，扫码后返回 `data.scanCode`；`POST /user/auth/v1/token_by_scan_code` 换 token |
| 3 | 短信验证码接口 | 实测 `POST /general/v1/send_phone_code` → `{"msg":"OK","status":0}`，接口存活 |
| 4 | 立绘/图标资源 | 实测 `torappu.prts.wiki/assets/char_avatar/{charId}.png`、`char_portrait/{charId}_1.png`、`skill_icon/skill_icon_{skillId}.png` 均 HTTP 200 |
| 5 | 静态游戏数据 | `yuanyan3060/ArknightsGameResource`、`weedy.prts.wiki/gacha_table.json` 可达 |
| 6 | 理智陈旧值外推 | 接口 `ap.current` 是上次同步快照，须用 `completeRecoveryTime` 反推：`max - ceil((recovery_ts - now)/360)`（方舟 6 分钟/点），满值回退 `max(current, max)` |
| 7 | 渲染约束 | 实测 AstrBot `local_strategy.render_custom_template` 直接 `raise NotImplementedError`，内置 `html_render` 仅支持远端 t2i 服务 → **游戏卡片必须自带 Playwright** |

### 3.1 关键实现约束（由实测推导）

- `scanUrl` 是 `hypergryph://` **自定义协议**而非 https 链接，插件必须自行生成二维码图片，无法直接丢链接。
- 扫码需按 `status` 轮询：`100`=未扫码，成功后取 `scanCode`。
- `gen_scan/login` 传入森空岛 `appCode=4ca99fa6b56cc2ba` 时 `enableScanAppList` 仅含森空岛，与后续 `oauth2/grant` 使用的 appCode 一致，应固定使用该值。

---

## 4. 架构

```
astrbot_plugin_arknights/
├── metadata.yaml                 # name/display_name/desc/version/author/repo/astrbot_version
├── _conf_schema.json             # WebUI 配置
├── requirements.txt              # httpx, pycryptodome, playwright, jinja2, qrcode, apscheduler
├── main.py                       # 指令路由、定时任务、订阅推送
├── core/
│   ├── skland.py                 # 森空岛：dId 生成、HMAC 签名、OAuth、绑定列表、签到、player/info
│   ├── hypergryph.py             # 鹰角账号：扫码登录、验证码登录、token 交换
│   ├── gamedata.py               # 静态表下载+缓存：character_table / skill_table / equip_table
│   ├── assets.py                 # torappu 资源 URL 组装 + 缓存
│   ├── render.py                 # Playwright + Jinja2 渲染（移植 endfield core/render.py）
│   └── store.py                  # 绑定/订阅持久化
├── templates/                    # note.html / sanity.html / operator.html / operator_list.html / help.html
├── resources/                    # 背景图、字体、职业图标
└── tests/                        # 单元测试 + fixture
```

### 4.1 模块职责与边界

| 模块 | 职责 | 对外接口 | 依赖 |
|---|---|---|---|
| `skland.py` | 把森空岛协议细节（设备指纹、签名、鉴权、业务接口）全部封装于此 | `bind_and_get_bindings(token)`、`sign(uid, game_id)`、`get_player_info(uid)` | httpx, pycryptodome |
| `hypergryph.py` | 只负责把「扫码/验证码」换成鹰角通行证 token | `create_qr()`、`poll_qr(scan_id)`、`send_code(phone)`、`login_by_code(phone, code)` | httpx, qrcode |
| `gamedata.py` | 静态表按需下载、磁盘缓存、镜像回退 | `get_char_table()`、`get_skill_table()`、`get_equip_table()` | httpx |
| `assets.py` | 由 charId/skillId 生成可访问图片 URL；本地缓存已下载图片 | `char_avatar(char_id)`、`char_portrait(char_id, phase)`、`skill_icon(skill_id)` | httpx |
| `render.py` | HTML→PNG，浏览器进程内复用，缓存清理 | `render_html(template, data)` | playwright, jinja2 |
| `store.py` | 绑定与订阅的原子读写 | `get_user(qq)`、`upsert_user(...)`、`list_subs(...)` | path_utils |

设计原则：**签名算法变化只影响 `skland.py` 一个文件**；`player/info` 的字段解读集中在 `main.py` 的解析函数中，不引入额外抽象层（遵循 KISS 与「无必要 helper」原则）。

### 4.2 数据流

```
用户指令
  → main.py 取当前会话用户的「主绑定」
  → skland.get_player_info(uid)         [带 TTL 缓存，默认 300s]
  → gamedata/assets 补全中文名与图片 URL
  → render.render_html(template, data)  [Playwright 截图]
  → Comp.Image 返回；渲染失败 → 降级纯文本摘要
```

---

## 5. 数据模型与安全

存储位置：`get_astrbot_plugin_data_path() / "astrbot_plugin_arknights" / "users.json"`，写入采用「临时文件 + `os.replace`」原子替换，文件权限 `0600`。

用户主键 `user_key` 固定取 `event.get_sender_id()`（平台用户标识）。绑定关系跟随用户而非会话，因此在任意群聊或私聊中查询都命中同一份绑定。

```json
{
  "users": {
    "<user_key>": {
      "token": "<鹰角通行证 token>",
      "skland_nickname": "探姬",
      "bindings": [
        {"uid": "68463675", "channel_master_id": "1", "channel_name": "官服", "nick_name": "探姬#9315"}
      ],
      "primary_uid": "68463675",
      "created_at": 1757980000
    }
  },
  "subs": {
    "sanity": ["<qq>"],
    "sign_groups": ["<group_id>"]
  }
}
```

安全要求：

- 绑定类指令**仅允许私聊**，群聊中直接拒绝并提示。
- 任何回复都不回显 token（`绑定列表` 只显示昵称/服/uid 尾号）。
- 扫码二维码与登录消息在超时、成功、被拒时**自动撤回**（对标终末地 2.0.0 行为）。
- 日志中 token / cred / sign 一律脱敏。

---

## 6. 指令清单（v1）

| 指令 | 说明 | 场景 |
|---|---|---|
| `ark` / `方舟帮助` | 帮助菜单（图片） | 全部 |
| `扫码绑定` | 生成二维码并轮询登录 | 私聊 |
| `验证码绑定 <手机号>` | 发送短信验证码 | 私聊 |
| `验证码绑定 <手机号> <验证码>` | 完成绑定 | 私聊 |
| `绑定列表` | 查看所有绑定账号 | 私聊 |
| `切换绑定 <序号>` | 切换主账号 | 私聊 |
| `删除绑定 <序号>` | 解绑指定账号 | 私聊 |
| `便签` | 账号总览卡片 | 全部 |
| `理智` | 理智与回满时间 | 全部 |
| `签到` | 手动执行森空岛签到 | 全部 |
| `订阅理智` / `取消订阅理智` | 理智回满推送开关 | 全部 |
| `订阅签到` / `取消订阅签到` | 群内自动签到结果通知 | 群 |
| `干员列表` | 持有干员图鉴 | 全部 |
| `<干员名>面板` | 单干员详情 | 全部 |

指令名较短，存在与其他插件冲突的可能：提供 `指令前缀` 配置项，并保证 `ark <子指令>` 命名空间形式同等可用。

`<干员名>面板` 通过 `@filter.regex()` 实现，需处理：干员不存在、重名、名字含特殊字符。

---

## 7. 渲染方案

移植 `endfield/core/render.py` 的成熟实现，保留其关键设计：

- Playwright 浏览器**进程内单例复用**，`asyncio.Lock` 保护初始化；`terminate()` 中释放。
- Jinja2 `Environment` 类级复用，避免重复编译。
- 模板中 `{{_res_path}}` 引用的本地 CSS/图片自动内联为 data URI。
- 截图按 `document.body.firstElementChild` 的 bounding box 裁剪，宽高 +2px 防截断。
- 渲染缓存目录定期清理超过 5 分钟的文件。
- 出图格式 JPEG（quality 40）以控制体积。

模板分工：`note.html`（便签）、`sanity.html`（理智）、`operator.html`（干员面板）、`operator_list.html`（干员图鉴）、`help.html`（帮助）。

**降级策略**：Playwright 不可用或渲染异常时，输出等价的纯文本摘要而非报错。

---

## 8. 错误处理

| 场景 | 处理 |
|---|---|
| token/cred 失效（401 或「用户未登录」） | 清理该用户绑定，提示重新绑定；同一 token 只清理一次避免日志刷屏 |
| 业务 `code != 0` | 提取 `message` 转为用户可读提示 |
| 网络错误 / 超时 | 重试 3 次（指数退避），仍失败则提示稍后再试 |
| 数据为旧快照 | 卡片上标注「数据时间：<storeTs>」；理智使用外推值而非裸值 |
| 渲染失败 | 降级为文本摘要 |
| 频繁请求风控 | `player/info` 按账号 TTL 缓存（默认 300s）；定时任务增加随机延迟；理智轮询间隔下限 10 分钟 |

---

## 9. 测试策略

**单元测试**（`tests/`，pytest）

- dId 签名：固定输入 → 固定 `tn` 值 / HMAC `sign` 值，防止回归。
- 理智外推：未满 / 刚好满 / 已超上限 / `completeRecoveryTime = -1` / 未来时间戳 五类边界。
- 干员筛选与分组：按职业、稀有度、精英化分组的正确性。
- 存储：并发写入下的原子性，权限为 `0600`。

**集成测试（mock）**：`httpx.MockTransport` 模拟森空岛响应，覆盖 `code != 0`、401、超时、畸形 JSON。

**渲染验证**：每个模板用 fixture 数据渲染出图，人工检查排版（不引入像素级快照，成本过高）。

**手工验收**：真实账号走通「扫码绑定 → 便签 → 理智 → 签到 → 干员列表 → 干员面板」。

---

## 10. 风险与对策

| 风险 | 等级 | 对策 |
|---|---|---|
| 验证码登录被风控/行为验证拦截 | **高** | 终末地插件已将「手机绑定」标注为暂不可用。**建议同时提供 `token 绑定 <token>` 作为零风险兜底**（约 10 行代码，参考插件均以此为默认路径） |
| 森空岛签名算法随版本变更 | 中 | 签名逻辑隔离在 `skland.py`，DES 表与指纹常量集中可热改；失败给出明确提示而非崩溃 |
| `player/info` 数据为旧快照 | 中 | 卡片标注数据时间；理智用外推公式 |
| Playwright 需额外安装 chromium（约 300MB） | 中 | 文档前置说明；首次渲染失败给出安装指引；渲染器懒加载 |
| 接口高频调用触发风控 | 中 | TTL 缓存 + 随机延迟 + 轮询间隔下限 |
| 指令名与其他插件冲突 | 低 | 可配置指令前缀 + `ark` 命名空间 |
| 短指令正则误触发（`xx面板`） | 低 | 精确匹配后缀并对未知名单给出友好提示 |

---

## 11. 里程碑

| 阶段 | 交付物 | 验收标准 |
|---|---|---|
| **P0 骨架与账号** | 插件骨架、`skland.py`、`hypergryph.py`、`store.py`、绑定/切换/删除指令、帮助菜单 | 能扫码绑定成功，`绑定列表` 正确，多账号可切换 |
| **P1 渲染与日常** | `render.py`、`assets.py`、`note.html`/`sanity.html`/`help.html`、`便签`、`理智`、`签到`、订阅推送 | 便签/理智出图正确；定时签到成功；理智满值能推送 |
| **P2 干员** | `gamedata.py`、`operator.html`/`operator_list.html`、`干员列表`、`<干员名>面板` | 干员图鉴与详情出图正确，静态表缓存可离线复用 |

每阶段完成后运行 `ruff format .` 与 `ruff check .`，并以 conventional commits 提交。

---

## 12. 待评审确认

1. **是否补充 `token 绑定 <token>` 兜底方式？** 验证码链路是唯一未实测的环节，且终末地插件已将其标注不可用，建议保留这条零风险路径。
2. 插件展示名定为「罗德岛终端」，仓库名 `astrbot_plugin_arknights`，是否合适？
3. 指令默认以不带前缀的短名暴露（`便签`/`理智`），同时保证 `ark <子指令>` 等价可用；若你更希望默认只保留 `ark` 命名空间以彻底避免冲突，请说明。

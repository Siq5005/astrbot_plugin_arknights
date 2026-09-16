# 罗德岛终端 · astrbot_plugin_arknights

基于**森空岛官方接口**的明日方舟 AstrBot 插件：账号绑定、便签、理智、签到、干员查询，全部输出为图片卡片。

不依赖任何第三方中转服务，直接对接鹰角/森空岛官方 API。

## 安装

1. 在 AstrBot 插件管理器中安装，或克隆到 `AstrBot/data/plugins`：

   ```bash
   cd AstrBot/data/plugins
   git clone <本仓库地址>
   ```

2. 安装无头浏览器内核（图片渲染必需）：

   ```bash
   playwright install chromium
   ```

3. 在 AstrBot WebUI 的插件配置中按需调整参数（渲染超时、数据缓存时间、自动签到时间等）。

## 绑定账号

三种方式任选，**均需私聊机器人**（防止账号凭证泄露到群聊）。

### 方式一：扫码绑定（推荐）

私聊发送 `扫码绑定`，用**森空岛 APP** 扫描机器人发来的二维码即可。二维码在超时、成功或被拒后会**自动撤回**。

### 方式二：验证码绑定

```
验证码绑定 <手机号>
验证码绑定 <手机号> <收到的验证码>
```

### 方式三：token 绑定（兜底）

1. 浏览器登录 [森空岛](https://www.skland.com/)，保持登录状态；
2. 同一浏览器新开标签页访问 <https://web-api.skland.com/account/info/hg>；
3. 复制返回 JSON 中 `content` 字段的值（不含引号）；
4. 私聊机器人发送 `token绑定 <该值>`。

> ⚠️ token 等同于账号登录凭证，请勿发到群聊或泄露给他人。怀疑泄露时在森空岛退出登录即可使其失效。

## 指令

| 指令 | 说明 | 场景 |
|---|---|---|
| `ark` / `方舟帮助` | 帮助菜单 | 全部 |
| `扫码绑定` | 扫码登录绑定 | 私聊 |
| `验证码绑定 <手机号> [验证码]` | 短信验证码绑定 | 私聊 |
| `token绑定 <token>` | token 绑定 | 私聊 |
| `绑定列表` | 查看所有绑定账号 | 私聊 |
| `切换绑定 <序号>` | 切换主账号 | 私聊 |
| `删除绑定 <序号>` | 解绑指定账号 | 私聊 |
| `便签` | 账号总览卡片 | 全部 |
| `理智` | 理智与回满时间 | 全部 |
| `签到` | 手动执行森空岛签到 | 全部 |
| `订阅理智` / `取消订阅理智` | 理智回满推送 | 全部 |
| `订阅签到` / `取消订阅签到` | 群内自动签到结果通知 | 群聊 |
| `干员列表` | 持有干员图鉴 | 全部 |
| `<干员名>面板` | 单干员详情 | 全部 |

## 常见问题

**图片渲染失败？**
确认已执行 `playwright install chromium`。渲染失败时插件会降级为文本摘要，不会报错崩掉。

**理智数值和游戏内不一致？**
森空岛接口返回的是**上次同步的快照**。插件会用恢复速率（6 分钟/点）从回满时刻反推当前理智，卡片上会标注数据时间。若偏差较大，在森空岛 APP 中同步一次账号即可。

**提示 token 失效？**
token 有过期时间。重新执行 `扫码绑定` 或 `token绑定` 即可。

**账号凭证是怎么存的？**
保存在 `AstrBot/data/plugin_data/astrbot_plugin_arknights/users.json`，文件权限 `0600`，仅本机可读，且不会在任何回复中回显。

## 范围边界

本插件专注**数据查询**。游戏自动化（MAA / MaaEnd）是独立子系统，不在本项目范围内——明日方舟的自动化可使用 [astrbot_plugin_maa](https://github.com/Hakuin123/astrbot_plugin_maa)。

## 开发与测试

```bash
# 单元测试（不需要 AstrBot 环境）
python -m pytest tests/ -v

# 代码风格
ruff format . && ruff check .

# 集成检查：通过 AstrBot 的实际导入路径加载插件，
# 并用桩数据驱动全部指令处理器（需在 AstrBot 仓库根目录下运行）
cd /path/to/AstrBot
.venv/bin/python /path/to/astrbot_plugin_arknights/tests/integration_check.py

# 渲染预览：把四张卡片渲染到 /tmp/akrender 供人工检查版式
python tests/render_preview.py
```

`core/` 下的模块**不导入 astrbot**，因此协议、解析、外推与分组逻辑都能脱离框架单测；`main.py` 只负责指令路由、定时任务与消息收发。

## 鸣谢

- [astrbot_plugin_skland](https://github.com/Azincc/astrbot_plugin_skland)（MIT）—— 森空岛设备指纹与请求签名算法的参考实现
- [AstrBot-SenKongDao-Check-in](https://github.com/Twilight719/AstrBot-SenKongDao-Check-in)（MIT）—— 理智回满外推公式与订阅推送思路
- [astrbot_plugin_endfield](https://github.com/Entropy-Increase-Team/astrbot_plugin_endfield)（**AGPL-3.0**）—— **仅作产品形态与功能设计参考，本项目未复用其任何代码**
- [astrbot_plugin_mrfz_haunting_query](https://github.com/R1ckyQaQ/astrbot_plugin_mrfz_haunting_query)（**AGPL-3.0**）—— 抽卡记录接口调研参考

> 需要特别说明：终末地插件与抽卡查询插件均为 AGPL-3.0。为保持本项目 MIT 许可，其代码（包括渲染器）均未被复制或移植，相关能力为独立实现。若将来需要复用它们的代码，本项目必须改为 AGPL-3.0 发布。

素材资源来自 PRTS Wiki 的官方游戏资源镜像（`torappu.prts.wiki`）。

## 许可

[MIT](LICENSE)

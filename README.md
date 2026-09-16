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

**唯一登录方式：扫码。** 私聊机器人发送 `方舟绑定`，用**森空岛 APP** 扫描机器人发来的二维码即可。二维码在超时、成功或被拒后会**自动撤回**。

> 绑定指令必须私聊使用，防止账号凭证泄露到群聊。插件不会保存你的密码，也不支持手机验证码或手工粘贴 token——只走森空岛官方扫码通道。

## 指令

> ⚠️ **所有指令都以 `方舟` 开头。**
> 这是刻意设计：[astrbot_plugin_endfield](https://github.com/Entropy-Increase-Team/astrbot_plugin_endfield)（终末地插件）注册了 `理智`、`便签`、`签到`、`扫码绑定`、`绑定列表` 等裸指令，还有一个匹配任意「xxx面板」的正则。如果本插件也用同名指令，同一条消息会被**两个插件同时处理**——你发 `扫码绑定` 会被终末地插件抢走，本插件却回你「还没有绑定账号」。加 `方舟` 前缀后两者互不干扰。

| 指令 | 说明 | 场景 |
|---|---|---|
| `方舟帮助` | 帮助菜单 | 全部 |
| `方舟绑定` | 扫码登录绑定（唯一登录方式） | 私聊 |
| `方舟绑定列表` | 查看所有绑定账号 | 私聊 |
| `方舟切换绑定 <序号>` | 切换主账号 | 私聊 |
| `方舟删除绑定 <序号>` | 解绑指定账号 | 私聊 |
| `方舟便签` | 账号总览卡片 | 全部 |
| `方舟理智` | 理智与回满时间 | 全部 |
| `方舟签到` | 手动执行森空岛签到 | 全部 |
| `方舟订阅理智` / `方舟取消订阅理智` | 理智回满推送 | 私聊 |
| `方舟订阅签到` / `方舟取消订阅签到` | 群内自动签到结果通知 | 群聊 |
| `方舟干员列表` | 持有干员图鉴 | 全部 |
| `方舟干员 <干员名>` | 单干员详情（别名：`方舟面板 <干员名>`） | 全部 |

### 日常玩法

| 指令 | 说明 | 场景 |
|---|---|---|
| `方舟基建` | 基建设施、干员心情、无人机与线索 | 全部 |
| `方舟剿灭` | 剿灭作战进度与本周合成玉 | 全部 |
| `方舟肉鸽` | 集成战略收藏品与投资进度 | 全部 |
| `方舟任务` | 每日 / 每周任务与周常奖励 | 全部 |
| `方舟公招` | 公开招募栏位状态 | 全部 |

### 抽卡

| 指令 | 说明 | 场景 |
|---|---|---|
| `方舟抽卡分析` | 总抽数、稀有度分布、六星序列、当前保底、UP / 歪判定、卡池分布 | 全部 |
| `方舟抽卡记录` | 最近的抽卡记录列表 | 全部 |

> 抽卡记录首次查询会下载卡池数据表（约 2.5MB，缓存 24 小时）。
> `方舟公招` 只展示栏位状态：森空岛接口不返回公招词条，而词条组合推荐需要可靠的招募池数据，在没有验证数据源之前本插件不做该推算，以免给出错误建议。

## 常见问题

**图片渲染失败？**
确认已执行 `playwright install chromium`。渲染失败时插件会降级为文本摘要，不会报错崩掉。

**理智数值和游戏内不一致？**
森空岛接口返回的是**上次同步的快照**。插件会用恢复速率（6 分钟/点）从回满时刻反推当前理智，卡片上会标注数据时间。若偏差较大，在森空岛 APP 中同步一次账号即可。

**提示凭证失效？**
森空岛的登录凭证有有效期。重新执行 `方舟绑定` 扫码即可。

**为什么我的 `扫码绑定` / `理智` / `便签` 没有反应？**
因为这些是终末地插件的指令，不是本插件的。本插件的指令一律以 `方舟` 开头，例如 `方舟绑定`、`方舟理智`、`方舟便签`。

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
# 并用桩数据驱动全部指令处理器，同时校验与终末地插件无指令冲突。
# 用 AstrBot 自己的解释器在 AstrBot 根目录（含 data/plugins 的那层）运行。
cd /path/to/AstrBot
ASTRBOT_ROOT=$PWD <astrbot-python> /path/to/astrbot_plugin_arknights/tests/integration_check.py

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

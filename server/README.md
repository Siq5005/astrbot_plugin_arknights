# arksource —— 明日方舟官方动态聚合服务

为 `astrbot_plugin_arknights` 提供「官方动态」数据的自建源。持有一份森空岛凭证，
后台轮询「官方」栏目并缓存，插件使用者无需任何鹰角账号。

## 为什么需要它

森空岛内容接口必须登录，且每个插件实例各自轮询会给上游带来成倍压力。
服务端集中缓存后，无论多少用户安装插件，上游只会看到这一台机器。

## 部署

前置条件：宿主机上要有 root 权限、已安装 Caddy，以及 `python3-venv`
（Debian/Ubuntu 上 `python3 -m venv` 缺它就会失败：`apt install python3-venv`）。

```bash
# 1. 代码
mkdir -p /opt/arksource && cd /opt/arksource
# 把仓库的 server/ 内容放到这里（rsync 或 git clone 后拷贝）

# 2. 依赖
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

# 3. 配置：生成 Key 并记下来，插件配置里要用同一个值
KEY=$(openssl rand -hex 24)
echo "API Key（请抄下来）: $KEY"
cat > arksource.env <<EOF
ARKSOURCE_API_KEY=$KEY
ARKSOURCE_HOST=127.0.0.1
ARKSOURCE_PORT=8788
ARKSOURCE_CREDENTIAL_FILE=/opt/arksource/credentials.json
ARKSOURCE_POLL_INTERVAL=1800
ARKSOURCE_WINDOW_HOURS=72
ARKSOURCE_STALE_MINUTES=60
EOF
chmod 600 arksource.env

# 4. 扫码登录（用森空岛 APP 扫终端二维码）
./venv/bin/python scripts/login.py

# 5. 服务
cp deploy/arksource.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now arksource

# 6. 反代：给 ark.youyou.ink 配 A 记录指向 162.211.183.29，再追加站点块。
#    改之前一定先备份——这台 Caddy 还反代着别的站点，写错会一起挂掉。
cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak-$(date +%Y%m%d-%H%M%S)
cat deploy/caddy-snippet.txt >> /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile && systemctl reload caddy
```

## 验证

```bash
set -a; . ./arksource.env; set +a   # 让下面的 $ARKSOURCE_API_KEY 有值
curl -s localhost:8788/api/ark/v1/health
curl -s -H "X-API-Key: $ARKSOURCE_API_KEY" localhost:8788/api/ark/v1/feed | head -c 400
curl -s -H "X-API-Key: $ARKSOURCE_API_KEY" https://ark.youyou.ink/api/ark/v1/feed | head -c 400
```

第 1 条不带 Key，故意不带；后两条没带对 Key 会返回 401。

## 接口

| 方法 | 路径 | 鉴权 | 说明 |
|:--|:--|:--|:--|
| GET | `/api/ark/v1/feed` | `X-API-Key` | 官方栏目条目，最新在前 |
| GET | `/api/ark/v1/health` | 无 | 缓存新鲜度，不含内容 |

`data.items[]` 字段：`id`、`title`、`kind`(1 视频 / 2 图集 / 3 文章)、
`published_at`(unix 秒)、`cover`、`images[]`、`text`、`url`、`tags[]`。

## 维护

- 凭证失效：看 `curl -s localhost:8788/api/ark/v1/health` 里的 `last_error`
  是否出现 `用户未登录`；是的话重跑 `scripts/login.py`。
- `core/skland.py` 或 `core/hypergryph.py` 变更后，用 `cp` 重新覆盖
  `app/skland_client.py` / `app/hypergryph_client.py`，并重启服务。
- `stale` 长时间为 `true`：看 `/var/log/arksource.log`（unit 里配了
  `StandardOutput=append:`，因为本机的 journald 读不到）。
- 森空岛会限流：日志里出现 `服务器开小差` 时先降低轮询频率（`ARKSOURCE_POLL_INTERVAL`
  调大）再排查，不要在报错时连续重试。

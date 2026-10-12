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

# odds_proxy 部署说明(zuqiu.xxcode.work)

零依赖 Node 代理:服务端保管 The Odds API key,全站共享 10 分钟缓存,上游故障退回旧缓存。
前端已内置探测:`/api/ping` 通 → 自动走代理(访客无需填 key);不通 → 回退现在的"自己填 key 直连"模式,**本地双击打开 HTML 的用法不受影响**。

## 一次性部署(在服务器 124.222.164.101 上)

```bash
# 1. 放文件
sudo mkdir -p /opt/odds-proxy
sudo chown ubuntu:ubuntu /opt/odds-proxy
scp odds_proxy.js ubuntu@124.222.164.101:/opt/odds-proxy/

# 2. 放 key(二选一:key.txt 或 systemd 环境变量)
echo "你的TheOddsAPIkey" > /opt/odds-proxy/key.txt
chmod 600 /opt/odds-proxy/key.txt

# 3. 装 Node(如果没有)
sudo apt install -y nodejs

# 4. systemd 服务
sudo tee /etc/systemd/system/odds-proxy.service <<'EOF'
[Unit]
Description=The Odds API cache proxy
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/opt/odds-proxy
ExecStart=/usr/bin/node /opt/odds-proxy/odds_proxy.js
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now odds-proxy
systemctl status odds-proxy   # 应显示 active (running)

# 5. nginx 挂到 /api/(在 zuqiu.xxcode.work 的 server 块里加)
#    /api/v4/sports/... → 127.0.0.1:8787/v4/sports/...
sudo tee /etc/nginx/snippets/odds-proxy.conf <<'EOF'
location /api/ {
    proxy_pass http://127.0.0.1:8787/;
    proxy_read_timeout 20s;
}
EOF
# 然后在 /etc/nginx/sites-enabled/ 里 zuqiu 的 server{} 中加一行:
#     include snippets/odds-proxy.conf;
sudo nginx -t && sudo systemctl reload nginx
```

## 验证

```bash
curl https://zuqiu.xxcode.work/api/ping
# → {"ok":true}
curl -sI "https://zuqiu.xxcode.work/api/v4/sports/" | grep -i x-cache
# 第一次 MISS,10 分钟内再请求 HIT
```

打开网站,不填 key 直接点「拉取赔率 + 回填赛果」应该能正常工作。

## 换 key / 运维

```bash
echo "新key" > /opt/odds-proxy/key.txt && sudo systemctl restart odds-proxy
journalctl -u odds-proxy -f          # 看日志
rm /opt/odds-proxy/cache.json && sudo systemctl restart odds-proxy   # 清缓存
```

## 安全设计

- 只放行 3 个只读路由(sports / odds / scores),路径参数白名单校验,不能当通用跳板
- 客户端传来的 apiKey 参数一律忽略,由服务端注入
- 只监听 127.0.0.1,外部必须经 nginx
- 缓存落盘 `cache.json`,重启不丢

## 对小程序的意义

小程序 request 域名要求 HTTPS + 备案域名白名单,不可能直连 the-odds-api.com。
这个代理就是小程序的数据后端雏形:届时把 `zuqiu.xxcode.work/api` 加进小程序
request 合法域名即可,前端逻辑(拉赔率→market_model.js 算概率)原样复用。

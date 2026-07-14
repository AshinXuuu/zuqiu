# 邮箱验证码登录 + 邀请白名单 部署说明

> **v2 更新(云端快照 + key 池)**:数据改为服务器统一存储 —— 只有管理员能点
> 「拉取」,拉到的赔率+赛果存成服务器上的 snapshot.json(仅保留最新一份,
> 几十~几百 KB,不占内存);其他用户打开网站自动读这份快照,只读,
> 「选择联赛」对他们只是本机显示筛选。管理后台新增 API key 池,可加多个 key,
> 额度用尽自动切换。
>
> **v2 升级步骤(已部署过 v1 的话)**:
> ```bash
> cd ~/Desktop/世界杯/outputs
> scp server/auth_server.js server/odds_proxy.js ubuntu@124.222.164.101:/opt/odds-proxy/
> ssh ubuntu@124.222.164.101 "sudo systemctl restart auth-server odds-proxy"
> ./deploy.sh "云端快照+key池"
> ```
> 首次会自动把 key.txt 迁移成 keys.json;之后在 /admin.html 里管理 key。

组件:`auth_server.js`(127.0.0.1:8788)负责发验证码、会话、邀请名单;
nginx 用 `auth_request` 把整站(含 /api 赔率代理)保护起来;
`login.html` 登录页、`admin.html` 管理后台(邀请/移除邮箱、看剩余额度)。
初始管理员:**ashinxu@yeah.net**(写在 data/whitelist.json 里,可改)。

## 第 1 步:传文件(Mac 上)

```bash
cd ~/Desktop/世界杯/outputs
scp server/auth_server.js ubuntu@124.222.164.101:/opt/odds-proxy/
```

## 第 2 步:配 SMTP(服务器上)

先去 mail.yeah.net 网页版:设置 → POP3/SMTP/IMAP → 开启 SMTP 服务,拿到**授权码**(不是邮箱登录密码)。

```bash
ssh ubuntu@124.222.164.101
cat > /opt/odds-proxy/smtp.json <<'EOF'
{
  "host": "smtp.yeah.net",
  "port": 465,
  "secure": true,
  "user": "ashinxu@yeah.net",
  "pass": "这里填SMTP授权码",
  "from": "noreply <ashinxu@yeah.net>"
}
EOF
chmod 600 /opt/odds-proxy/smtp.json
```

> 注:邮箱服务商要求发件地址=登录账号,所以地址只能是你的邮箱,但收件人看到的显示名是 noreply。

## 第 3 步:systemd 服务(服务器上)

```bash
sudo tee /etc/systemd/system/auth-server.service <<'EOF'
[Unit]
Description=Email code auth server
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/opt/odds-proxy
ExecStart=/usr/bin/node /opt/odds-proxy/auth_server.js
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now auth-server
curl -s http://127.0.0.1:8788/auth/ping   # 应返回 {"ok":true}
```

## 第 4 步:替换 nginx 配置(服务器上)

整文件替换(去掉了旧的 Basic Auth 密码框和旧 include):

```bash
sudo tee /etc/nginx/sites-available/zuqiu <<'EOF'
server {
    server_name zuqiu.xxcode.work;
    root /var/www/zuqiu;
    index index.html;

    # 登录服务
    location /auth/ {
        proxy_pass http://127.0.0.1:8788;
    }
    location = /auth/check {
        internal;
        proxy_pass http://127.0.0.1:8788/auth/check;
        proxy_pass_request_body off;
        proxy_set_header Content-Length "";
    }
    # 赔率代理(需登录)
    location /api/ {
        auth_request /auth/check;
        proxy_pass http://127.0.0.1:8787/;
        proxy_read_timeout 20s;
    }
    # 登录页放行
    location = /login.html { }
    # 其余全部需登录,未登录跳登录页
    location / {
        auth_request /auth/check;
        error_page 401 = @login;
        try_files $uri $uri/ =404;
    }
    location @login { return 302 /login.html; }

    listen 443 ssl; # managed by Certbot
    ssl_certificate /etc/letsencrypt/live/zuqiu.xxcode.work/fullchain.pem; # managed by Certbot
    ssl_certificate_key /etc/letsencrypt/live/zuqiu.xxcode.work/privkey.pem; # managed by Certbot
    include /etc/letsencrypt/options-ssl-nginx.conf; # managed by Certbot
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem; # managed by Certbot
}
server {
    if ($host = zuqiu.xxcode.work) {
        return 301 https://$host$request_uri;
    } # managed by Certbot
    listen 80;
    server_name zuqiu.xxcode.work;
    return 404; # managed by Certbot
}
EOF
sudo nginx -t && sudo systemctl reload nginx
```

## 第 5 步:发前端(Mac 上)

```bash
cd ~/Desktop/世界杯/outputs
./deploy.sh "邮箱验证码登录+管理后台"
```

## 验证

1. 浏览器打开 https://zuqiu.xxcode.work → 应跳到登录页
2. 输 ashinxu@yeah.net → 获取验证码 → 查邮箱 → 登录 → 进看板
3. 打开 https://zuqiu.xxcode.work/admin.html → 邀请朋友邮箱
4. 朋友用受邀邮箱登录;未受邀邮箱会提示"不在邀请名单"

## 运维

```bash
journalctl -u auth-server -f                      # 日志(发信失败会在这里)
cat /opt/odds-proxy/data/whitelist.json           # 名单(admins=管理员)
sudo systemctl restart auth-server                # 改配置后重启
```

- 加管理员:编辑 whitelist.json 的 admins 数组后重启
- 会话 30 天有效,存 data/sessions.json;验证码 10 分钟有效、60 秒重发间隔、错 5 次作废
- 如果收不到信:先看 journalctl 报错;yeah.net 授权码是否正确;新邮箱账号日发送量有限制,大量邀请建议换腾讯云邮件推送(SES),只需改 smtp.json

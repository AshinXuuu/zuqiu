# 部署到自己的服务器 + 登录保护(Nginx Basic Auth)

服务器 124.222.164.101 · 域名 zuqiu.xxcode.work · 登录账号 xxuxx

---

## 0. 三个前提(不做后面一定失败)

1. **DNS 解析**:到你的域名服务商,给 `zuqiu.xxcode.work` 加一条 **A 记录 → 124.222.164.101**。
   生效后,在本机跑 `ping zuqiu.xxcode.work` 应能看到这个 IP。
2. **云服务器安全组**:124.222.x 是腾讯云。去腾讯云控制台 → 这台机器 → 安全组,
   **放行入站 80 和 443 端口**。(只在服务器里开 ufw 不够,云控制台这层最常被忘。)
3. 准备好登录密码(你给的 xxx777)。建议之后换一个更强的;别在任何聊天/公开处贴真实密码。

---

## 1. 本机:把网页传到服务器(在你 Mac 的终端跑)

```
scp ~/Desktop/世界杯/outputs/index.html ubuntu@124.222.164.101:/tmp/index.html
```

## 2. 登录服务器

```
ssh ubuntu@124.222.164.101
```
以下命令都在**服务器里**跑。

## 3. 安装 Nginx 和密码工具

```
sudo apt update
sudo apt install -y nginx apache2-utils
```

## 4. 放置网页 + 创建唯一登录账号

```
sudo mkdir -p /var/www/zuqiu
sudo mv /tmp/index.html /var/www/zuqiu/index.html

# 创建登录账号 xxuxx,回车后按提示输入两遍密码(xxx777)
sudo htpasswd -c /etc/nginx/.htpasswd xxuxx
```
> `-c` 表示新建密码文件。以后想再加账号,去掉 `-c`:`sudo htpasswd /etc/nginx/.htpasswd 新账号`。
> 唯一账号就只建这一个即可。

## 5. 配置站点 + 登录拦截

```
sudo tee /etc/nginx/sites-available/zuqiu >/dev/null <<'EOF'
server {
    listen 80;
    server_name zuqiu.xxcode.work;

    root /var/www/zuqiu;
    index index.html;

    auth_basic "请登录";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        try_files $uri $uri/ =404;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/zuqiu /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

到这里访问 `http://zuqiu.xxcode.work` 就会先弹**登录框**,输 xxuxx / 你的密码才能进。
(若服务器开了 ufw 防火墙:`sudo ufw allow 'Nginx Full'`)

## 6. 上 HTTPS(重要:不加密码会明文传输)

```
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d zuqiu.xxcode.work
```
按提示填邮箱、同意条款、选 **2(把 http 自动跳转到 https)**。
证书 90 天自动续期,无需手动。

完成后访问:**https://zuqiu.xxcode.work** 🎉

---

## 以后更新网页

本机重新传一次,覆盖即可(不用动 Nginx):
```
scp ~/Desktop/世界杯/outputs/index.html ubuntu@124.222.164.101:/tmp/index.html
ssh ubuntu@124.222.164.101 "sudo mv /tmp/index.html /var/www/zuqiu/index.html"
```

## 安全要点

- **务必先上 HTTPS(第6步)再实际使用**:否则登录密码和你填的 The Odds API key 会明文走网络。
- 网页里**不要硬编码 API key**;保持现在"网页里手填、只存浏览器本地"的方式。
- 想改密码:`sudo htpasswd /etc/nginx/.htpasswd xxuxx`(重设),然后 `sudo systemctl reload nginx`。
- 想看是否有人在试登录:`sudo tail -f /var/log/nginx/access.log`。

## 常见卡点

- 打不开/超时 → 八成是第 0 步的**安全组没放行 80/443**,或 DNS 还没生效。
- `nginx -t` 报错 → 多半是第 5 步的配置粘贴不全,重新整段粘一次。
- certbot 失败 → 先确认 `http://zuqiu.xxcode.work` 能打开(DNS+80 端口通)再重试。

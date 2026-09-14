#!/usr/bin/env bash
# 打包出一个可以直接上传到服务器的目录。
#
#   cd web && ./scripts/pack.sh
#
# 产出 web/upload/，里面分好了「传哪些」和「怎么传」：
#   upload/site/   → 整个目录的内容传到网站根目录
#   upload/proxy/  → 仅在用阿里云百炼这类不支持跨域的服务时才需要
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
OUT="$ROOT/upload"

BOLD=$'\033[1m'; DIM=$'\033[2m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; OFF=$'\033[0m'
step() { printf "\n%s▸ %s%s\n" "$BOLD" "$1" "$OFF"; }
info() { printf "  %s%s%s\n" "$DIM" "$1" "$OFF"; }
warn() { printf "  %s! %s%s\n" "$YELLOW" "$1" "$OFF"; }

# ── 词库 ────────────────────────────────────────────────────
# 缺了它构建不会报错，但产物里没有词库，难词模式要到运行时才 404。
step "检查难词词库"
if [ -f public/vocab.json ]; then
  info "public/vocab.json 已存在（$(du -h public/vocab.json | cut -f1)）"
elif [ -f ../data/vocab.db ]; then
  info "从 ../data/vocab.db 生成…"
  python3 scripts/build_web_vocab.py
else
  warn "找不到词库，打出来的包将不支持难词模式。"
  warn "补齐办法（在仓库根目录）："
  warn "  cd backend && ../.venv/bin/python -m scripts.fetch_wordlists"
  warn "  cd backend && ../.venv/bin/python -m scripts.build_vocab"
  warn "  cd web && python3 scripts/build_web_vocab.py"
fi

# ── 构建 ────────────────────────────────────────────────────
step "构建前端"
[ -d node_modules ] || npm install --silent
npm run build --silent >/dev/null
info "完成"

# ── 组装 ────────────────────────────────────────────────────
step "组装上传包"
rm -rf "$OUT"
mkdir -p "$OUT/site" "$OUT/proxy"

# macOS 会到处生成 .DS_Store，别让它混进上传包
( cd dist && find . -name '.DS_Store' -delete )
cp -R dist/. "$OUT/site/"

cp proxy/server.mjs "$OUT/proxy/server.mjs"

cat > "$OUT/proxy/pdf-proxy.service" <<'UNIT'
# 转发代理的 systemd 单元。只在用阿里云百炼这类不支持跨域的服务时才需要。
#
#   sudo cp pdf-proxy.service /etc/systemd/system/
#   sudo mkdir -p /opt/pdf-proxy && sudo cp server.mjs /opt/pdf-proxy/
#   # 改下面的 ORIGIN 为你的站点地址，然后：
#   sudo systemctl enable --now pdf-proxy

[Unit]
Description=PDF 对照 转发代理
After=network.target

[Service]
ExecStart=/usr/bin/node /opt/pdf-proxy/server.mjs
Environment=UPSTREAM=https://dashscope.aliyuncs.com/compatible-mode/v1
Environment=ORIGIN=https://改成你的站点地址
Environment=PORT=8788
Restart=always
RestartSec=3
User=www-data
# 代理不需要写任何文件
ProtectSystem=strict
PrivateTmp=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
UNIT

cat > "$OUT/nginx.conf.example" <<'NGINX'
# PDF 对照 · 纯前端版　Nginx 配置示例
#
# 把 upload/site/ 里的内容放到 root 指向的目录，就这些。

server {
    listen 443 ssl http2;
    server_name pdf.example.com;          # 改成你的域名

    # ssl_certificate     /etc/letsencrypt/live/pdf.example.com/fullchain.pem;
    # ssl_certificate_key /etc/letsencrypt/live/pdf.example.com/privkey.pem;

    root /var/www/pdf;
    index index.html;

    # 6.9 MB 能压到约 2 MB，务必打开
    gzip on;
    gzip_comp_level 6;
    gzip_min_length 1024;
    gzip_types text/css application/javascript text/javascript application/json;

    # 文件名带内容哈希，可以长期缓存；换版本时文件名会变
    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # 词库文件名固定，用较短的缓存，换词库后能自动更新
    location = /vocab.json {
        expires 7d;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }

    # ── 以下仅在用阿里云百炼这类不支持跨域的服务时才需要 ──
    # 启用后，在网页「设置」里把 Base URL 填成
    #   https://pdf.example.com/proxy/v1
    #
    # location /proxy/ {
    #     proxy_pass http://127.0.0.1:8788/;
    #     proxy_set_header Authorization $http_authorization;
    #     proxy_read_timeout 300s;        # 翻译长段落可能较慢
    # }
}
NGINX

# ── 上传说明 ────────────────────────────────────────────────
SITE_SIZE=$(du -sh "$OUT/site" | cut -f1)
cat > "$OUT/README.md" <<MD
# 上传包

由 \`web/scripts/pack.sh\` 生成。

## 传什么

**把 \`site/\` 目录里的全部内容，传到网站根目录。** 就这一件事。

\`\`\`sh
rsync -av --delete --exclude '.DS_Store' site/ user@服务器:/var/www/pdf/
\`\`\`

大小 ${SITE_SIZE}，开了 gzip 之后实际传输约 2 MB。
服务器上不需要 Node、不需要源码、不需要数据库。

\`nginx.conf.example\` 是配置示例，按注释改域名和证书路径即可。

## 要不要 proxy/

看你用哪个翻译服务 —— 浏览器直接调用它，所以它必须允许跨域。

| 服务 | 是否需要 proxy/ |
|---|---|
| DeepSeek、硅基流动、智谱、OpenRouter、OpenAI | **不需要**，删掉 proxy/ 即可 |
| 阿里云百炼（通义千问） | **需要** |

需要的话：

\`\`\`sh
scp proxy/server.mjs user@服务器:/opt/pdf-proxy/
scp proxy/pdf-proxy.service user@服务器:/tmp/
# 服务器上：改 pdf-proxy.service 里的 ORIGIN 为你的站点地址
sudo cp /tmp/pdf-proxy.service /etc/systemd/system/
sudo systemctl enable --now pdf-proxy
\`\`\`

然后放开 \`nginx.conf.example\` 末尾那段 \`location /proxy/\`，重载 Nginx，
最后在网页「设置」里把 Base URL 填成 \`https://你的域名/proxy/v1\`。

服务器需要 Node 18+。代理约 90 行、零依赖、不存储任何数据。

## 部署到子路径

要放在 \`https://example.com/pdf/\` 这种子路径下，得回源码改 \`vite.config.js\`：

\`\`\`js
base: "/pdf/",     // 默认 "./"
\`\`\`

改完重新跑 \`./scripts/pack.sh\`。不改会白屏。

## 访客数据去哪

PDF 与译文只在访客浏览器内存里，刷新即消失，**从不上传到你的服务器**。
即使用了 proxy，经过的也只是抽取出的文本（翻译本身绕不开），密钥原样转发不留存。

服务器上不产生任何用户数据。

---

更详细的说明见仓库里的 [web/DEPLOY.md](../DEPLOY.md)。
MD

# ── 收尾 ────────────────────────────────────────────────────
# macOS 会在任何被访问过的目录里留下 .DS_Store，组装完要再清一遍整个包
find "$OUT" -name '.DS_Store' -delete

printf "\n%s✓ 打包完成%s  %s%s%s\n" "$GREEN" "$OFF" "$DIM" "$OUT" "$OFF"
printf "\n%s上传这一个目录的内容即可：%s\n" "$BOLD" "$OFF"
printf "  %s/site/   (%s)\n\n" "$OUT" "$SITE_SIZE"
find "$OUT" -type f | sed "s|$OUT/|  |" | sort
printf "\n%s先读 %s/README.md%s\n\n" "$DIM" "$OUT" "$OFF"

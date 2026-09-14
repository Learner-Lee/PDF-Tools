# 部署到服务器

[← 返回 web/README](README.md)

**结论先行：只需要上传 `dist/` 一个目录（约 7 MB）。服务器上不需要 Node、不需要源码、不需要数据库。**

唯一的例外是翻译服务不支持跨域时（比如阿里云百炼），要额外跑一个转发代理 —— 见方案 B。

---

## 先确认走哪个方案

浏览器直接调用你选的 LLM 服务，所以对方必须允许跨域。**实测结果**：

| 你用的服务 | 走哪个方案 |
|---|---|
| DeepSeek、硅基流动、智谱、OpenRouter、OpenAI | **方案 A** — 纯静态，服务器上什么进程都不用跑 |
| 阿里云百炼（通义千问） | **方案 B** — 需要额外跑一个转发代理 |

换成 CORS 友好的服务，部署会简单很多。

---

## 一条命令打包

不想逐步操作的话，直接生成一个可以上传的目录：

```sh
cd web && ./scripts/pack.sh
```

产出 `web/upload/`，里面分好了传哪些、怎么传：

```
upload/
├── README.md                上传说明
├── nginx.conf.example       Nginx 配置示例
├── site/                    ← 传这个目录的内容到网站根目录
└── proxy/                   ← 仅用阿里云百炼时需要
    ├── server.mjs
    └── pdf-proxy.service    systemd 单元
```

脚本会自动补齐词库、清掉 `.DS_Store`。下面是手动分步的说明。

## 方案 A：纯静态

### 1. 本机构建

```sh
cd web
npm install
python3 scripts/build_web_vocab.py   # 生成难词词库，见下方「坑 1」
npm run build
```

### 2. 上传 `dist/` 的全部内容

构建产物只有 4 个文件：

```
dist/
├── index.html                              4 KB
├── vocab.json                            5.1 MB   难词词库
└── assets/
    ├── index-*.js                         552 KB   应用
    ├── index-*.css                         12 KB
    └── pdf.worker.min-*.mjs               1.3 MB   pdf.js 解析线程
```

合计 6.9 MB，开了 gzip 之后传输约 2 MB。

```sh
rsync -av --delete dist/ user@服务器:/var/www/pdf/
```

`--delete` 会清掉上一版留下的旧文件（文件名带内容哈希，不清理会越积越多）。

### 3. Nginx

```nginx
server {
    listen 443 ssl;
    server_name pdf.example.com;

    root /var/www/pdf;
    index index.html;

    # 开 gzip，6.9 MB 能压到约 2 MB
    gzip on;
    gzip_types text/css application/javascript application/json text/javascript;
    gzip_min_length 1024;

    # 带哈希的静态资源可以长期缓存
    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # 词库不带哈希，用协商缓存，换了词库能自动更新
    location = /vocab.json {
        expires 7d;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

没有用前端路由，所以 `try_files` 只是兜底，不配也能跑。

**到此结束。** 没有后端进程，不用 systemd，多人同时访问天然支持。

---

## 方案 B：另加转发代理（用阿里云百炼时）

除了方案 A 的全部内容，再上传一个文件：

```
web/proxy/server.mjs      约 90 行，零依赖
```

服务器需要 Node 18+。

### 启动

```sh
UPSTREAM=https://dashscope.aliyuncs.com/compatible-mode/v1 \
ORIGIN=https://pdf.example.com \
PORT=8788 \
node server.mjs
```

`ORIGIN` 填你的站点地址，别用 `*` —— 那等于允许任何网站借你的代理转发。

### 做成常驻服务

```ini
# /etc/systemd/system/pdf-proxy.service
[Unit]
Description=PDF 对照 转发代理
After=network.target

[Service]
ExecStart=/usr/bin/node /opt/pdf-proxy/server.mjs
Environment=UPSTREAM=https://dashscope.aliyuncs.com/compatible-mode/v1
Environment=ORIGIN=https://pdf.example.com
Environment=PORT=8788
Restart=always
User=www-data

[Install]
WantedBy=multi-user.target
```

```sh
sudo systemctl enable --now pdf-proxy
```

### Nginx 反代到同域

在方案 A 的 server 块里加一段，这样前端填相对路径就行，不用再处理跨域：

```nginx
location /proxy/ {
    proxy_pass http://127.0.0.1:8788/;
    proxy_set_header Authorization $http_authorization;
}
```

然后在网页「设置」里把 Base URL 填成 `https://pdf.example.com/proxy/v1`。

### 代理会碰到什么数据

- **不会碰 PDF** —— 文件始终在访客浏览器里，从不上传
- 只转发抽取出的文本给 LLM 厂商 —— 这是翻译本身绕不开的
- 密钥由浏览器随请求带来、原样转发，代理不读取、不保存
- 不落盘、不打印请求体、无数据库

---

## 三个容易踩的坑

### 坑 1：`vocab.json` 不在 git 里

它是生成的，`.gitignore` 排除了。**在服务器上 clone 仓库直接构建，构建会成功，但产物里没有词库** —— 难词模式要到运行时才 404，构建期没有任何提示。

所以构建前必须先跑：

```sh
python3 scripts/build_web_vocab.py
```

它读取仓库根目录的 `data/vocab.db`，而那份由本地版的
`backend/scripts/fetch_wordlists.py` + `build_vocab.py` 生成。

**最省事的做法是在本机构建好再上传 `dist/`**，服务器上就不必装 Python 和这一整条链路。

### 坑 2：部署到子路径要改 `base`

放在 `https://example.com/pdf/` 这种子路径下时，先改 `vite.config.js`：

```js
base: "/pdf/",     // 默认是 "./"
```

改完重新构建。不改的话资源路径会指错，页面白屏。

### 坑 3：别把 `.DS_Store` 传上去

macOS 会在目录里生成它。`rsync` 加上排除：

```sh
rsync -av --delete --exclude '.DS_Store' dist/ user@服务器:/var/www/pdf/
```

---

## 更新流程

```sh
cd web
git pull
npm install                          # 依赖有变动时
python3 scripts/build_web_vocab.py   # 词表有更新时才需要
npm run build
rsync -av --delete --exclude '.DS_Store' dist/ user@服务器:/var/www/pdf/
```

访客的浏览器会自动拿到新版本 —— 资源文件名带内容哈希，变了就不会命中旧缓存。

---

## 访客的数据在哪

| 数据 | 位置 | 是否经过你的服务器 |
|---|---|---|
| PDF 文件 | 访客浏览器内存 | **否**，刷新即消失 |
| 译文 | 访客浏览器内存 | 方案 A 否；方案 B 文本经代理转发 |
| 生词本 | 访客浏览器内存 | 否，刷新即消失 |
| API 密钥 | 访客本机 localStorage | 否（方案 B 下随请求原样转发，不留存） |
| 难词词库 | 访客本机 IndexedDB | 是（静态资源，不含用户数据） |

服务器上不产生任何用户数据，也就没有备份与合规负担。

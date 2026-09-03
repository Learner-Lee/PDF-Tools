#!/usr/bin/env node
/**
 * 极小转发代理：只为不支持跨域的 LLM 服务（如阿里云百炼）而存在。
 *
 * 设计上刻意受限：
 *   - **上游地址由服务端配置**，客户端不能指定 —— 否则就成了任人使用的开放代理
 *   - 不存储任何东西：不落盘、不打印请求体、无数据库
 *   - 只放行 /models 与 /chat/completions 两个路径
 *   - 密钥由浏览器随请求带来，原样转发，代理自身不持有
 *
 *   node proxy/server.mjs
 *
 * 环境变量：
 *   UPSTREAM  上游 base_url（必填），如 https://dashscope.aliyuncs.com/compatible-mode/v1
 *   PORT      监听端口，默认 8788
 *   ORIGIN    允许的来源，默认 *（部署到公网时建议改成你的站点地址）
 */
import http from "node:http";

const UPSTREAM = (process.env.UPSTREAM || "").replace(/\/+$/, "");
const PORT = Number(process.env.PORT || 8788);
const ORIGIN = process.env.ORIGIN || "*";

if (!UPSTREAM) {
  console.error("需要设置 UPSTREAM，例如：\n" +
    "  UPSTREAM=https://dashscope.aliyuncs.com/compatible-mode/v1 node proxy/server.mjs");
  process.exit(1);
}

const ALLOWED = new Set(["/models", "/chat/completions"]);

function cors(res) {
  res.setHeader("Access-Control-Allow-Origin", ORIGIN);
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Authorization, Content-Type");
  res.setHeader("Access-Control-Max-Age", "86400");
}

const server = http.createServer(async (req, res) => {
  cors(res);
  if (req.method === "OPTIONS") return res.writeHead(204).end();

  const path = new URL(req.url, "http://x").pathname.replace(/^\/v1/, "");
  if (!ALLOWED.has(path)) {
    res.writeHead(404, { "Content-Type": "application/json" });
    return res.end(JSON.stringify({ error: { message: `不支持的路径 ${path}` } }));
  }

  const chunks = [];
  for await (const c of req) chunks.push(c);
  const body = Buffer.concat(chunks);

  try {
    const upstream = await fetch(UPSTREAM + path, {
      method: req.method,
      headers: {
        "Content-Type": "application/json",
        // 密钥来自浏览器，原样转发；代理不读取、不保存
        ...(req.headers.authorization ? { Authorization: req.headers.authorization } : {}),
      },
      body: req.method === "POST" ? body : undefined,
    });
    const text = await upstream.text();
    res.writeHead(upstream.status, { "Content-Type": "application/json; charset=utf-8" });
    res.end(text);
  } catch (e) {
    res.writeHead(502, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: { message: `转发失败：${e.message}` } }));
  }
});

server.listen(PORT, () => {
  console.log(`转发代理已启动  http://localhost:${PORT}/v1`);
  console.log(`  上游   ${UPSTREAM}`);
  console.log(`  来源   ${ORIGIN}`);
  console.log("  不存储任何数据；密钥由浏览器带来并原样转发。");
});

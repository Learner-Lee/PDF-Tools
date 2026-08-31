# PDF 对照

英文 PDF 的中文对照阅读器。左边是原版页面，右边是逐段对齐的中文。

当前支持**文字版 PDF**。扫描件需要 OCR，尚未实现，上传时会明确提示。

## 快速开始

```bash
# 后端
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt

# 前端（首次需要构建一次，之后后端会直接托管）
cd frontend && npm install && npm run build && cd ..

# 启动
cd backend && ../.venv/bin/python -m uvicorn app.main:app --port 8731
```

打开 http://localhost:8731 即可。

### 配置翻译服务

首次打开点右上角**设置**，填入任意 OpenAI 兼容端点：

- 选一个预设（阿里云百炼 / DeepSeek / 智谱 / 硅基流动 / OpenAI / Ollama / llama.cpp …）
- 填 API 密钥
- 点**获取模型列表**，从真实可用的模型里挑
- 点**测试连接**看样例译文与 token 消耗

密钥只存在本机 `storage/cache.db`，不会进入 git。

也可以在项目根建 `.env`（参考 `.env.example`）预置一份，首次启动会自动导入。

> **通义千问用户注意**：qwen3.x 全系默认开启思考模式，翻译成本会涨约 40 倍。
> 预设已带上 `{"enable_thinking": false}`，请勿删除。

### 本地模型

llama.cpp 或 Ollama 起好服务后，在设置里填 `http://localhost:8080/v1`
（Ollama 是 `http://localhost:11434/v1`），密钥留空即可。

## 开发

```bash
cd backend && ../.venv/bin/python -m uvicorn app.main:app --port 8731 --reload
cd frontend && npm run dev        # http://localhost:5273，已配好 /api 代理
```

测试：`cd backend && ../.venv/bin/python -m pytest tests/ -q`

## 花销与缓存

翻译结果按「源文本 + 端点 + 模型」缓存在本地 SQLite：

- 对照阅读与全文翻译**共用同一份缓存**，看过的页导出时不重复付费
- 重开同一份 PDF 不会重新调用 API
- 换端点或换模型才会重新翻译；仅改档案名称不会

参考文献默认不翻译（可在代码中调整），文档中原本就是中文的段落自动跳过。
一篇 19 页双栏论文实测约 6 万字符待翻译。

端点地址变更导致缓存失效时，可用迁移工具救回：

```bash
cd backend && ../.venv/bin/python -m scripts.remap_cache --list
../.venv/bin/python -m scripts.remap_cache --from 旧标识 --to-active
```

## 设计与实现说明

见 [DESIGN.md](DESIGN.md)。其中附录记录了在真实论文上验证时，
被数据推翻的若干设计假设与修正过程。

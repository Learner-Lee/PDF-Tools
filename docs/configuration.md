# 配置指南

[← 返回 README](../README.md)

## 翻译服务

启动后点右上角**设置**：

1. 选一个预设（阿里云百炼 / DeepSeek / Moonshot / 智谱 / 硅基流动 /
   OpenAI / OpenRouter / Ollama / llama.cpp / 自定义）
2. 填 API 密钥
3. 点**获取模型列表** —— 从该服务真实可用的模型里挑，不必猜模型名
4. 点**测试连接** —— 看样例译文与本次 token 消耗

可以建多份档案随时切换。密钥只存在本机 `storage/cache.db`，不会进 git，
也不会发往除你所选服务之外的任何地方；界面上一律显示遮蔽值。

### 通义千问用户注意

`qwen3.x` 全系默认开启**思考模式**。实测翻译同一句话：

| 配置 | completion_tokens |
|---|---|
| 默认 | 300+ |
| `enable_thinking: false` | **7** |

批量翻译整本 PDF 时差异约 **40 倍成本**。预设里已带
`{"enable_thinking": false}`，请勿删除。

这个参数是通义特有的，发给 OpenAI 之类的端点会被拒绝 —— 遇到这种情况会自动
去掉重试，所以填错也不至于完全用不了。

### 本地模型

llama.cpp 或 Ollama 起好服务后，base_url 填：

- llama.cpp — `http://localhost:8080/v1`
- Ollama — `http://localhost:11434/v1`

**密钥留空**。密钥为空时不会发送 `Authorization` 头，某些本地服务收到空
Bearer 反而会报错。

### 用 .env 预置

也可以在项目根目录建 `.env`（参考 `.env.example`），库里没有档案时首次启动
会自动导入：

```sh
QWEN_API_KEY=sk-...
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL_TRANSLATE=qwen3.6-flash
QWEN_MODEL_GLOSS=qwen3.6-flash
```

`.env` 已被 `.gitignore` 屏蔽。占位符（如 `sk-xxxxxxxx`）会被当成没填。

## 难词词库

难词模式需要一份本地词库。安装时加 `WITH_VOCAB=1` 可一并构建，或事后补：

```sh
cd backend
../.venv/bin/python -m scripts.fetch_wordlists   # 下载公开词表，约 70 MB
../.venv/bin/python -m scripts.build_vocab       # 编译成 data/vocab.db，约 39 MB
```

Windows 把 `../.venv/bin/python` 换成 `..\.venv\Scripts\python`。

不构建也能正常用对照翻译与导出，只是难词模式会提示去构建。词库全程离线工作，
不调用任何 API。

### 数据来源

| 文件 | 来源 | 许可 |
|---|---|---|
| `ecdict.csv` | [skywind3000/ECDICT](https://github.com/skywind3000/ECDICT) | MIT |
| `lemma.en.txt` | 同上（BNC 语料生成的词形还原表） | MIT |
| `coca20000.txt` | [mahavivo/english-wordlists](https://github.com/mahavivo/english-wordlists) | 公开整理 |

编译后 40 万词条，其中 1.75 万条有 COCA 名次、19.9 万条有音标，全部带中文释义。
低频词全部保留 —— 恰恰是它们最需要释义。

原始文件与编译产物都不入库，用上面两条命令随时重建。

## 花销与缓存

翻译结果按「**源文本 + 端点 + 模型**」缓存在本地 SQLite：

- 对照阅读、全文翻译与导出**共用同一份缓存**，看过的页不会重复付费
- 重开同一份 PDF 不会重新调用 API
- 换端点或换模型才会重新翻译；仅改档案名称不会

参考文献默认不翻译（设置里可开），文档中原本就是中文的段落自动跳过。
一篇 19 页双栏论文实测约 5.9 万字符待翻译，打开参考文献翻译后增加约 9 千字符。

### 缓存迁移

端点地址变更会让旧缓存失效，可用工具救回：

```sh
cd backend
../.venv/bin/python -m scripts.remap_cache --list          # 看各标识下有多少条
../.venv/bin/python -m scripts.remap_cache --from 旧标识 --to-active
```

## 数据存放位置

全部在项目目录内，卸载就是删掉整个目录。

```
.env                  你的密钥（已被 .gitignore 屏蔽）
storage/uploads/      上传的 PDF 原件
storage/exports/      导出的中文 PDF 与 Markdown
storage/cache.db      翻译缓存、Provider 档案、生词本、设置
data/vocab.db         难词词库（可重建）
data/wordlists/raw/   词库原始文件（可重删）
```

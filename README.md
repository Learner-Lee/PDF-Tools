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

### 构建词库（难词模式需要）

```bash
cd backend
../.venv/bin/python -m scripts.fetch_wordlists   # 下载公开词表，约 70 MB
../.venv/bin/python -m scripts.build_vocab       # 编译成 data/vocab.db，约 39 MB
```

不构建也能用对照翻译，只是难词模式会提示去构建。词库全程离线，不调用任何 API。

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

文档中原本就是中文的段落自动跳过。一篇 19 页双栏论文实测约 5.9 万字符待翻译。

**参考文献默认不翻译**，在设置里可以打开。打开后按条整条翻译（同一条的
悬挂缩进续行会先并回来），实测该论文增加 36 条 / 约 9 千字符。

端点地址变更导致缓存失效时，可用迁移工具救回：

```bash
cd backend && ../.venv/bin/python -m scripts.remap_cache --list
../.venv/bin/python -m scripts.remap_cache --from 旧标识 --to-active
```

## 导出

顶栏「导出 PDF」产出**保留原版式的中文 PDF**：栏数、图片与图表位置、
标题层级、页码水印全部留在原处，只把文字换成中文。公式、代码、表格、
原本就是中文的段落原样保留。输出仍可搜索复制，不是图片。

「Markdown」是无条件附带的保底产物：丢版式但内容完整、可二次编辑 ——
版面重建在某些文档上失真时，至少还有能读的东西。

需要先完成全文翻译（未译比例过高会直接拒绝导出并说明还差多少段）。
实测 19 页论文导出 28 页，多出的页来自译文比原文长的段落自然溢出。

## 难词模式

顶栏切到「难词」：整篇保持英文，超出你词汇量的词加一条虚下划线，
并在词后直接跟上简短中文，如 `mitigate（温和,缓和）`。
**点击**该词（点中文也一样）弹出卡片，含完整释义、音标、词频档位，
可收进生词本并导出 CSV / Anki。再点一次、点别处或按 Esc 收起。

两套等级基准，在设置里自选：

- **按词频档位**：认识 COCA 前 3 千 / 5 千 / 8 千 / 1.5 万词
- **按考试大纲**：中考 / 高考 / 四级 / 六级 / 考研 / 雅思 / 托福 / GRE

判定全部离线完成，不花钱。专有名词、术语表词条、纯数字与公式代码块自动排除；
给不出释义的词不做标记 —— 点开是空的下划线只会打断阅读。

### 词库数据来源

| 文件 | 来源 | 许可 |
|---|---|---|
| ecdict.csv | [skywind3000/ECDICT](https://github.com/skywind3000/ECDICT) | MIT |
| lemma.en.txt | 同上（BNC 语料生成的词形还原表） | MIT |
| coca20000.txt | [mahavivo/english-wordlists](https://github.com/mahavivo/english-wordlists) | 公开整理 |

编译后 40 万词条，其中 1.75 万条有 COCA 名次、19.9 万条有音标，全部带中文释义。
原始文件与编译产物都不入库，用上面两条命令随时重建。

## 设计与实现说明

见 [DESIGN.md](DESIGN.md)。其中附录记录了在真实论文上验证时，
被数据推翻的若干设计假设与修正过程。

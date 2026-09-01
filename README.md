# PDF 对照

英文 PDF 的中文对照阅读器。左边是原版页面，右边是逐段对齐的中文。

- **对照阅读** — 滚到哪译到哪，两栏双向同步，栏间对位带标出当前段落的对应关系
- **难词模式** — 整篇保持英文，只给超出你词汇量的词加注中文，可收进生词本导出 Anki
- **导出** — 保留原版式的中文 PDF，另附一份 Markdown 保底

当前支持**文字版 PDF**。扫描件需要 OCR，尚未实现，上传时会明确提示。

---

## 一条命令部署

不用先 clone，直接跑：

**macOS / Linux**

```bash
curl -fsSL https://raw.githubusercontent.com/Learner-Lee/PDF-Tools/main/install.sh | bash
```

**Windows（PowerShell）**

```powershell
irm https://raw.githubusercontent.com/Learner-Lee/PDF-Tools/main/install.ps1 | iex
```

脚本会依次完成：检查环境 → 克隆代码 → 建虚拟环境装依赖 → 构建前端 →
生成配置 → 启动服务，最后打开 <http://localhost:8731> 即可使用。
再次执行会拉取更新并复用已有环境，可反复运行。

> 从网上直接管道执行脚本，等于把执行权交给了那个地址。
> 想先看清楚再跑：
> `curl -fsSL https://raw.githubusercontent.com/Learner-Lee/PDF-Tools/main/install.sh -o install.sh`
> 看过之后 `bash install.sh`。

### 开关

先设环境变量再执行即可。

| 变量 | 作用 |
|---|---|
| `WITH_VOCAB=1` | 一并构建难词词库（额外下载约 70MB，编译成 39MB） |
| `NO_START=1` | 只装不启动 |
| `PORT=8080` | 换监听端口 |
| `DIR=my-pdf` | 换克隆目录名 |

```bash
# 例：连难词词库一起装好，装完不自动启动
curl -fsSL https://raw.githubusercontent.com/Learner-Lee/PDF-Tools/main/install.sh \
  | WITH_VOCAB=1 NO_START=1 bash
```

Windows 对应写法：

```powershell
$env:WITH_VOCAB=1; $env:NO_START=1
irm https://raw.githubusercontent.com/Learner-Lee/PDF-Tools/main/install.ps1 | iex
```

### 前置要求

脚本会自己检查，缺了会直接告诉你装什么。

- **Python 3.10+** — <https://www.python.org/downloads/>（Windows 记得勾 Add to PATH）
- **Node 18+** — <https://nodejs.org/>
- **Git** — <https://git-scm.com/downloads>

### 之后怎么启动

装过一次以后，在项目目录里：

```bash
.venv/bin/python -m uvicorn app.main:app --app-dir backend --port 8731     # macOS / Linux
.venv\Scripts\python -m uvicorn app.main:app --app-dir backend --port 8731  # Windows
```

或者再跑一次 `install.sh` / `install.ps1`，它会跳过已完成的步骤直接启动。

---

## 配置翻译服务

启动后点右上角**设置**，填入任意 OpenAI 兼容端点：

1. 选一个预设（阿里云百炼 / DeepSeek / 智谱 / 硅基流动 / OpenAI / OpenRouter / Ollama / llama.cpp…）
2. 填 API 密钥
3. 点**获取模型列表**，从该服务真实可用的模型里挑
4. 点**测试连接**，看样例译文与本次 token 消耗

密钥只存在本机 `storage/cache.db`，不会进 git，也不会发往除你所选服务之外的任何地方。

> **通义千问用户注意**：qwen3.x 全系默认开启思考模式，翻译成本会涨约 40 倍。
> 预设里已带 `{"enable_thinking": false}`，请勿删除。

**本地模型**：llama.cpp 或 Ollama 起好服务后，base_url 填
`http://localhost:8080/v1`（Ollama 是 `http://localhost:11434/v1`），密钥留空。

也可以在项目根目录的 `.env` 里预置一份（参考 `.env.example`），首次启动会自动导入。

---

## 难词词库

难词模式需要一份本地词库，安装时加 `WITH_VOCAB=1` 可一并构建，或事后补：

```bash
cd backend
../.venv/bin/python -m scripts.fetch_wordlists   # 下载公开词表，约 70 MB
../.venv/bin/python -m scripts.build_vocab       # 编译成 data/vocab.db，约 39 MB
```

Windows 把 `../.venv/bin/python` 换成 `..\.venv\Scripts\python`。

不构建也能正常用对照翻译与导出，只是难词模式会提示去构建。
词库全程离线工作，不调用任何 API。

**数据来源**

| 文件 | 来源 | 许可 |
|---|---|---|
| ecdict.csv | [skywind3000/ECDICT](https://github.com/skywind3000/ECDICT) | MIT |
| lemma.en.txt | 同上（BNC 语料生成的词形还原表） | MIT |
| coca20000.txt | [mahavivo/english-wordlists](https://github.com/mahavivo/english-wordlists) | 公开整理 |

编译后 40 万词条，其中 1.75 万条有 COCA 名次、19.9 万条有音标，全部带中文释义。
原始文件与编译产物都不入库，用上面两条命令随时重建。

---

## 怎么用

### 对照阅读

拖一份英文 PDF 进来（或从「最近打开」选）。左栏是原版页面，右栏是中文，
**滚到哪译到哪**，两栏双向同步。栏间那条带子把当前段落在两侧的纵向跨度连起来 ——
中文排版长度约为英文的 0.6~0.8 倍，两栏几何上永远对不齐，带子的收放就是这个长度差。

顶栏「翻译全文」把整篇一次译完，与对照阅读共用同一份缓存。

### 难词模式

顶栏切到「难词」：整篇保持英文，超出你词汇量的词加一条虚下划线，
并在词后跟一段简短中文，如 `mitigate（温和,缓和）`。
**点击**该词（点中文也一样）弹出卡片，含完整释义、音标、词频档位，
可收进生词本。再点一次、点别处或按 Esc 收起。

两套等级基准，在设置里自选：

- **按词频档位** — 认识 COCA 前 3 千 / 5 千 / 8 千 / 1.5 万词
- **按考试大纲** — 中考 / 高考 / 四级 / 六级 / 考研 / 雅思 / 托福 / GRE

判定全部离线完成，不花钱。专有名词、术语表词条、公式代码块自动排除；
给不出释义的词不做标记 —— 点开是空的下划线只会打断阅读。

生词本可导出 CSV 或 Anki（导入时选「字段由制表符分隔」）。

### 导出

顶栏「导出 PDF」产出**保留原版式的中文 PDF**：栏数、图片与图表位置、
标题层级、页码水印全部留在原处，只把文字换成中文。公式、代码、表格、
原本就是中文的段落原样保留。输出仍可搜索复制，不是图片。

「Markdown」是无条件附带的保底产物：丢版式但内容完整、可二次编辑 ——
版面重建在某些文档上失真时，至少还有能读的东西。

需要先完成全文翻译（未译比例过高会拒绝导出并说明还差多少段）。
实测 19 页论文导出 28 页，多出的页来自译文比原文长的段落自然溢出。

---

## 花销与缓存

翻译结果按「源文本 + 端点 + 模型」缓存在本地 SQLite：

- 对照阅读、全文翻译与导出**共用同一份缓存**，看过的页不会重复付费
- 重开同一份 PDF 不会重新调用 API
- 换端点或换模型才会重新翻译；仅改档案名称不会

参考文献默认不翻译（设置里可开），文档中原本就是中文的段落自动跳过。
一篇 19 页双栏论文实测约 5.9 万字符待翻译；打开参考文献翻译后增加约 9 千字符。

译文不理想或换了模型时，点顶栏「重新翻译」清空重来 —— 命中缓存的部分不会重新花钱。

端点地址变更导致缓存失效时，可用迁移工具救回：

```bash
cd backend
../.venv/bin/python -m scripts.remap_cache --list
../.venv/bin/python -m scripts.remap_cache --from 旧标识 --to-active
```

---

## 数据都在哪

全部在项目目录内，卸载就是删掉整个目录。

```
.env                  你的密钥（已被 .gitignore 屏蔽）
storage/uploads/      上传的 PDF 原件
storage/exports/      导出的中文 PDF 与 Markdown
storage/cache.db      翻译缓存、Provider 档案、生词本、设置
data/vocab.db         难词词库（可重建）
data/wordlists/raw/   词库原始文件（可重删）
```

---

## 开发

```bash
# 后端热重载
.venv/bin/python -m uvicorn app.main:app --app-dir backend --port 8731 --reload

# 前端开发服务器（已配好 /api 代理到 8731）
cd frontend && npm run dev        # http://localhost:5273
```

测试：

```bash
cd backend && ../.venv/bin/python -m pytest tests -q
```

---

## 实现说明

见 [DESIGN.md](DESIGN.md)。其中的附录记录了在真实论文上验证时，
被数据推翻的若干设计假设与修正过程 —— 比如内置中文字体把拉丁字母排成全角、
行距照搬固定值导致大面积溢页、参考文献之后的附录被整片误判等。

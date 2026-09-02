# PDF 对照

把英文 PDF 变成能读的中文：左边是原版页面，右边是逐段对齐的译文。

- **对照阅读** — 滚到哪译到哪，两栏双向同步，栏间对位带标出当前段落的对应关系
- **难词模式** — 整篇保持英文，只给超出你词汇量的词加注中文，可收进生词本导出 Anki
- **原版式导出** — 栏数、图表位置、标题层级全部留在原处，只把文字换成中文

翻译服务不绑定厂商：任何 OpenAI 兼容端点都能用，也可以接本地模型。

## 当前状态

可用，三个功能都已完成，55 个测试。当前只支持**文字版 PDF** —— 扫描件需要 OCR，
尚未实现，上传时会明确提示。实机在 macOS 上验证，Windows 侧按跨平台约束审过代码但未做真机测试。

## 运行

### 一条命令

不必先 clone。脚本会检查环境、克隆代码、装依赖、构建前端、生成配置并启动服务。

**macOS / Linux**

```sh
curl -fsSL https://raw.githubusercontent.com/Learner-Lee/PDF-Tools/main/install.sh | bash
```

**Windows（PowerShell）**

```powershell
irm https://raw.githubusercontent.com/Learner-Lee/PDF-Tools/main/install.ps1 | iex
```

跑完在浏览器打开 `http://localhost:8731`。再次执行会拉取更新并复用已有环境，可反复运行。

想先看清楚脚本再跑，就下载下来读一遍：
`curl -fsSL https://raw.githubusercontent.com/Learner-Lee/PDF-Tools/main/install.sh -o install.sh`

### 从源码运行

```sh
git clone https://github.com/Learner-Lee/PDF-Tools.git
cd PDF-Tools
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cd frontend && npm install && npm run build && cd ..
.venv/bin/python -m uvicorn app.main:app --app-dir backend --port 8731
```

需要 Python 3.10+、Node 18+、Git。Windows 把 `.venv/bin/` 换成 `.venv\Scripts\`。

### 开关

安装脚本读环境变量，管道运行时同样生效：

```sh
curl -fsSL .../install.sh | WITH_VOCAB=1 NO_START=1 bash
```

| 变量 | 作用 |
|---|---|
| `WITH_VOCAB=1` | 一并构建难词词库（额外下载约 70MB，编译成 39MB） |
| `NO_START=1` | 只装不启动 |
| `PORT=8080` | 换监听端口 |
| `DIR=my-pdf` | 换克隆目录名 |

## 配置

启动后点右上角**设置**，选一个预设（阿里云百炼 / DeepSeek / 智谱 / 硅基流动 /
OpenAI / OpenRouter / Ollama / llama.cpp…），填密钥，点「获取模型列表」挑模型，
再点「测试连接」验证。密钥只存在本机，不会进 git。

详见 [配置指南](docs/configuration.md)。

## 文档

- [使用指南](docs/guide.md) — 三个功能怎么用
- [配置指南](docs/configuration.md) — 翻译服务、难词词库、花销与缓存、数据存放位置
- [开发](docs/development.md) — 目录结构、热重载、测试
- [设计文档](DESIGN.md) — 架构与实现说明，附录记录了在真实论文上被数据推翻的设计假设

## 反馈

欢迎通过 [GitHub Issues](https://github.com/Learner-Lee/PDF-Tools/issues) 提交问题与建议。

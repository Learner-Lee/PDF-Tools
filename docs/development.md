# 开发

[← 返回 README](../README.md)

## 目录结构

```
backend/app/
  parser/      PDF → 结构化文档模型（块提取、栏检测、阅读顺序、表格、段落合并）
  translator/  Provider 抽象、批处理、缓存、术语表
  vocab/       难词判定、词库访问、生词本
  renderer/    原版式 PDF 与 Markdown 导出
  services/    文档服务（上传、解析、持久化）
  api/         HTTP 接口
backend/scripts/   词表下载与编译、缓存迁移
frontend/src/
  components/  PdfPane / TransPane / HardWordPane / Gutter / Settings / VocabBook
  lib/api.js   接口封装
```

解析层是三个功能的共同地基：它把 PDF 拆成带类型、bbox、栏号与阅读顺序的块，
翻译层、难词层、渲染层都建在这之上。

## 热重载

```sh
# 后端
.venv/bin/python -m uvicorn app.main:app --app-dir backend --port 8731 --reload

# 前端（已配好 /api 代理到 8731）
cd frontend && npm run dev        # http://localhost:5273
```

前端不跑 dev server 也可以 —— `npm run build` 之后后端会直接托管构建产物。

## 测试

```sh
cd backend && ../.venv/bin/python -m pytest tests -q
```

55 个测试。依赖真实样本 PDF 或词库的测试在文件缺失时会自动跳过，不会失败。

测试覆盖的重点是那些**被真实数据推翻过的判定**：连字符消歧、表格识别的兜底、
难词等级的单调性、排版回流的行距与障碍避让。这些地方每一处都踩过坑，
详见 [DESIGN.md](../DESIGN.md) 的附录。

## 解析器版本

`backend/app/parser/pipeline.py` 里的 `PARSER_VERSION` 在解析逻辑变更时必须递增。

已持久化的文档模型据此自动失效并重新解析 —— 否则用户升级后仍会看到旧的解析
结果（例如附录被误判为参考文献）。翻译缓存不受影响，重解后仍会命中。

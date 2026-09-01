const j = async (r) => {
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try {
      const b = await r.json();
      msg = b.detail || b.message || msg;
    } catch {}
    throw new Error(msg);
  }
  return r.json();
};

export const api = {
  health: () => fetch("/api/health").then(j),

  upload(file, onProgress) {
    // 用 XHR 而非 fetch：需要上传进度
    return new Promise((resolve, reject) => {
      const fd = new FormData();
      fd.append("file", file);
      const x = new XMLHttpRequest();
      x.open("POST", "/api/documents");
      x.upload.onprogress = (e) =>
        e.lengthComputable && onProgress?.(e.loaded / e.total);
      x.onload = () => {
        let body = {};
        try { body = JSON.parse(x.responseText); } catch {}
        x.status >= 200 && x.status < 300
          ? resolve(body)
          : reject(new Error(body.detail || `上传失败（HTTP ${x.status}）`));
      };
      x.onerror = () => reject(new Error("上传失败，请检查后端服务是否在运行"));
      x.send(fd);
    });
  },

  list: () => fetch("/api/documents").then(j),
  doc: (id) => fetch(`/api/documents/${id}`).then(j),
  pages: (id) => fetch(`/api/documents/${id}/pages`).then(j),
  fileUrl: (id) => `/api/documents/${id}/file`,

  /** 导出译稿。返回 null 表示已开始下载，否则返回给用户看的错误说明。 */
  async exportDoc(id, format, filename) {
    const r = await fetch(`/api/documents/${id}/export?format=${format}`);
    if (!r.ok) {
      try {
        return (await r.json()).detail || `导出失败（HTTP ${r.status}）`;
      } catch {
        return `导出失败（HTTP ${r.status}）`;
      }
    }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    return null;
  },

  retranslate: (id) =>
    fetch(`/api/documents/${id}/retranslate`, { method: "POST" }).then(j),

  translate: (id, pages) =>
    fetch(`/api/documents/${id}/translate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pages }),
    }).then(j),

  /** 全文翻译，SSE 逐条回报进度 */
  async translateAll(id, onEvent) {
    const r = await fetch(`/api/documents/${id}/translate-all`, { method: "POST" });
    if (!r.ok) throw new Error(await r.text());
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop();
      for (const p of parts) {
        const line = p.split("\n").find((l) => l.startsWith("data: "));
        if (line) onEvent(JSON.parse(line.slice(6)));
      }
    }
  },

  options: () => fetch("/api/settings/options").then(j),
  saveOptions: (o) =>
    fetch("/api/settings/options", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(o),
    }).then(j),

  vocabProfile: () => fetch("/api/vocab/profile").then(j),
  saveVocabProfile: (p) =>
    fetch("/api/vocab/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(p),
    }).then(j),
  hardWords: (id, pages) =>
    fetch(`/api/vocab/documents/${id}/hardwords`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pages }),
    }).then(j),
  book: () => fetch("/api/vocab/book").then(j),
  addWord: (w) =>
    fetch("/api/vocab/book", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(w),
    }).then(j),
  removeWord: (lemma) =>
    fetch(`/api/vocab/book/${encodeURIComponent(lemma)}`, { method: "DELETE" }).then(j),
  exportBookUrl: (format) => `/api/vocab/book/export?format=${format}`,

  presets: () => fetch("/api/settings/presets").then(j),
  providers: () => fetch("/api/settings/providers").then(j),
  saveProvider: (p) =>
    fetch("/api/settings/providers", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(p),
    }).then(j),
  deleteProvider: (id) =>
    fetch(`/api/settings/providers/${id}`, { method: "DELETE" }).then(j),
  activateProvider: (id) =>
    fetch(`/api/settings/providers/${id}/activate`, { method: "POST" }).then(j),
  fetchModels: (p) =>
    fetch("/api/settings/providers/models", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(p),
    }).then(j),
  testProvider: (p) =>
    fetch("/api/settings/providers/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(p),
    }).then(j),
};

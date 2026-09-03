/**
 * 常见 OpenAI 兼容服务。cors 字段是**实测结果**，不是猜的。
 *
 * 纯前端版直接从浏览器调用这些服务，所以对方必须返回跨域许可头，
 * 否则请求会被浏览器拦下。不标出来的话，用户选了百炼会在"测试连接"时莫名失败。
 */
export const PRESETS = [
  { key: "deepseek", label: "DeepSeek", baseUrl: "https://api.deepseek.com/v1",
    cors: true, extraBody: {} },
  { key: "siliconflow", label: "硅基流动", baseUrl: "https://api.siliconflow.cn/v1",
    cors: true, extraBody: {}, note: "聚合多家开源模型" },
  { key: "zhipu", label: "智谱 GLM", baseUrl: "https://open.bigmodel.cn/api/paas/v4",
    cors: true, extraBody: {} },
  { key: "openrouter", label: "OpenRouter", baseUrl: "https://openrouter.ai/api/v1",
    cors: true, extraBody: {}, note: "聚合网关" },
  { key: "openai", label: "OpenAI", baseUrl: "https://api.openai.com/v1",
    cors: true, extraBody: {} },
  { key: "dashscope", label: "阿里云百炼（通义千问）",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    cors: false, extraBody: { enable_thinking: false },
    note: "不支持浏览器直连，需配合 proxy/ 里的转发代理使用；" +
          "qwen3.x 默认开思考，务必保留 enable_thinking:false，否则成本涨约 40 倍" },
  { key: "ollama", label: "Ollama（本机）", baseUrl: "http://localhost:11434/v1",
    cors: true, extraBody: {}, note: "需设 OLLAMA_ORIGINS=* 允许跨域；密钥留空" },
  { key: "custom", label: "自定义", baseUrl: "", cors: null, extraBody: {} },
];

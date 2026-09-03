/**
 * 用户配置：存本机 localStorage。
 *
 * 与 PDF、译文不同 —— 那些只在内存里，刷新即消失；
 * 配置若不留，每次刷新都要重填密钥，用不下去。
 */
const KEY = "pdf-duizhao-config";

export const DEFAULT_CONFIG = {
  presetKey: "deepseek",
  baseUrl: "https://api.deepseek.com/v1",
  apiKey: "",
  model: "",
  extraBody: {},
  translateReferences: false,
  basis: "coca",
  cocaTier: 5000,
  examLevel: "cet6",
};

export function loadConfig() {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? { ...DEFAULT_CONFIG, ...JSON.parse(raw) } : { ...DEFAULT_CONFIG };
  } catch {
    return { ...DEFAULT_CONFIG };
  }
}

export function saveConfig(cfg) {
  try { localStorage.setItem(KEY, JSON.stringify(cfg)); } catch { /* 隐私模式下忽略 */ }
}

export function isConfigured(cfg) {
  return Boolean(cfg.baseUrl && cfg.model
    && (cfg.apiKey || /localhost|127\.0\.0\.1/.test(cfg.baseUrl)));
}

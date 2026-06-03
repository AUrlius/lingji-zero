import os from 'node:os';
import path from 'node:path';

function envInt(key, defaultVal) {
  const s = process.env[key];
  if (s === undefined || s === '') return defaultVal;
  const v = parseInt(s, 10);
  return Number.isNaN(v) ? defaultVal : v;
}

function envInt64(key, defaultVal) {
  const s = process.env[key];
  if (s === undefined || s === '') return defaultVal;
  const v = parseInt(s, 10);
  return Number.isNaN(v) ? defaultVal : v;
}

function envDurationMs(key, defaultMs) {
  const s = process.env[key];
  if (!s) return defaultMs;
  const m = s.match(/^(\d+)(ms|s|m|h)?$/);
  if (!m) return defaultMs;
  const n = parseInt(m[1], 10);
  const unit = m[2] || 's';
  const mult = { ms: 1, s: 1000, m: 60000, h: 3600000 }[unit] ?? 1000;
  return n * mult;
}

/** @returns {import('./types.js').GatewayConfig} */
export function defaultConfig() {
  return {
    port: envInt('LINGJI_PORT', 8766),
    authToken: process.env.LINGJI_AUTH_TOKEN ?? '',
    heartbeatTimeoutMs: envDurationMs('LINGJI_HEARTBEAT_TIMEOUT', 120000),
    offlineQueueSize: 100,
    maxMessageSize: 65536,
    fileMaxSizeBytes: envInt64('LINGJI_FILE_MAX_BYTES', 50 * 1024 * 1024),
    fileTtlMs: envDurationMs('LINGJI_FILE_TTL', 3600000),
    fileMaxDownloads: envInt('LINGJI_FILE_MAX_DOWNLOADS', 10),
    fileStoreDir:
      process.env.LINGJI_FILE_STORE_DIR ||
      path.join(os.tmpdir(), 'lingji-files'),
    webIndexPath: process.env.LINGJI_WEB_INDEX_PATH ?? '',
  };
}

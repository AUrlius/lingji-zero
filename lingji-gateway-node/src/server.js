import fs from 'node:fs';
import fsp from 'node:fs/promises';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defaultConfig } from './config.js';
import { Hub } from './hub/hub.js';
import { FilesHandler } from './handler/files.js';
import { WSHandler } from './handler/ws.js';
import { OfflineQueue } from './queue/offline.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function resolveWebIndex(cfg) {
  if (cfg.webIndexPath && fs.existsSync(cfg.webIndexPath)) {
    return cfg.webIndexPath;
  }
  const sibling = path.resolve(__dirname, '../../lingji-gateway/web/index.html');
  if (fs.existsSync(sibling)) return sibling;
  return null;
}

/**
 * @param {Partial<import('./config.js').GatewayConfig>} [overrides]
 */
export function createServer(overrides = {}) {
  const cfg = { ...defaultConfig(), ...overrides };
  const hub = new Hub(cfg.heartbeatTimeoutMs);
  const queue = new OfflineQueue(cfg.offlineQueueSize);
  const files = new FilesHandler(cfg);
  const ws = new WSHandler(hub, cfg, queue);
  const webIndex = resolveWebIndex(cfg);

  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url ?? '/', `http://${req.headers.host ?? 'localhost'}`);

    if (url.pathname === '/health') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(
        JSON.stringify({ status: 'ok', online: hub.len(), port: cfg.port, runtime: 'node' }),
      );
      return;
    }

    if (url.pathname === '/files' || url.pathname.startsWith('/files/')) {
      await files.handle(req, res);
      return;
    }

    if (url.pathname === '/') {
      if (!webIndex) {
        res.writeHead(404);
        res.end('index.html not found');
        return;
      }
      const html = await fsp.readFile(webIndex, 'utf8');
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end(html);
      return;
    }

    res.writeHead(404);
    res.end('not found');
  });

  ws.attach(server);

  return {
    cfg,
    hub,
    queue,
    files,
    ws,
    server,
    async listen(port = cfg.port) {
      await new Promise((resolve, reject) => {
        server.once('error', reject);
        server.listen(port, resolve);
      });
      const addr = server.address();
      return typeof addr === 'object' && addr ? addr.port : port;
    },
    async close() {
      files.store.stop();
      hub.stop();
      await new Promise((resolve) => server.close(resolve));
    },
  };
}

export async function startGateway(overrides = {}) {
  const app = createServer(overrides);
  const port = await app.listen(app.cfg.port);
  console.log(`[Gateway-Node] listening on :${port} auth=${Boolean(app.cfg.authToken)}`);
  return app;
}

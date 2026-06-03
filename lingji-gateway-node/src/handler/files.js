import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import Busboy from 'busboy';

function randomToken(bytes = 16) {
  return crypto.randomBytes(bytes).toString('hex');
}

export function sanitizeUploadFilename(name) {
  const base = path.basename(String(name || '').trim());
  if (!base || base === '.' || base === '..') return 'upload';
  return base;
}

export class FileStore {
  /** @param {import('../config.js').GatewayConfig} cfg */
  constructor(cfg) {
    this.cfg = cfg;
    /** @type {Map<string, object>} */
    this.files = new Map();
    this._stop = false;
    this._timer = setInterval(() => this.purgeExpired(), 5 * 60 * 1000);
    fs.mkdirSync(cfg.fileStoreDir, { recursive: true, mode: 0o700 });
  }

  stop() {
    this._stop = true;
    clearInterval(this._timer);
  }

  purgeExpired() {
    const now = Date.now();
    for (const [id, f] of this.files) {
      if (now > f.expiresAt) {
        fs.unlink(f.path, () => {});
        this.files.delete(id);
      }
    }
  }
}

export class FilesHandler {
  /** @param {import('../config.js').GatewayConfig} cfg */
  constructor(cfg) {
    this.cfg = cfg;
    this.store = new FileStore(cfg);
  }

  authOK(req) {
    if (!this.cfg.authToken) return true;
    const auth = req.headers.authorization;
    if (auth === `Bearer ${this.cfg.authToken}`) return true;
    const url = new URL(req.url, 'http://localhost');
    return url.searchParams.get('token') === this.cfg.authToken;
  }

  downloadAuthOK(req, f) {
    const url = new URL(req.url, 'http://localhost');
    const tok = url.searchParams.get('token');
    if (tok) {
      return tok === f.downloadTok || tok === this.cfg.authToken;
    }
    return this.authOK(req);
  }

  maxBytes() {
    return this.cfg.fileMaxSizeBytes > 0
      ? this.cfg.fileMaxSizeBytes
      : 50 * 1024 * 1024;
  }

  /** @param {import('node:http').IncomingMessage} req @param {import('node:http').ServerResponse} res */
  async handle(req, res) {
    const url = new URL(req.url, 'http://localhost');
    const sub = url.pathname.replace(/^\/files\/?/, '');

    if (!sub) {
      if (req.method !== 'POST') {
        res.writeHead(405);
        res.end('method not allowed');
        return;
      }
      return this.handleUpload(req, res);
    }

    if (req.method !== 'GET') {
      res.writeHead(405);
      res.end('method not allowed');
      return;
    }
    return this.handleDownload(req, res, sub.split('/')[0]);
  }

  /** @param {import('node:http').IncomingMessage} req @param {import('node:http').ServerResponse} res */
  handleUpload(req, res) {
    if (!this.authOK(req)) {
      res.writeHead(401);
      res.end('unauthorized');
      return;
    }

    const maxBytes = this.maxBytes();
    const busboy = Busboy({
      headers: req.headers,
      limits: { fileSize: maxBytes + 1024 },
    });

    let name = 'download.bin';
    let altName = '';
    /** @type {import('node:stream').Writable | null} */
    let dest = null;
    let destPath = '';
    let written = 0;
    let fileId = '';
    let dlTok = '';
    let mimeType = 'application/octet-stream';
    let failed = false;

    busboy.on('field', (fieldname, val) => {
      if (fieldname === 'name') altName = val;
    });

    busboy.on('file', (fieldname, file, info) => {
      if (fieldname !== 'file' || failed) {
        file.resume();
        return;
      }
      name = sanitizeUploadFilename(info.filename || '');
      if (name === 'upload' && !info.filename) name = 'download.bin';
      if (altName) name = sanitizeUploadFilename(altName);
      mimeType = info.mimeType || 'application/octet-stream';

      fileId = randomUUID();
      dlTok = randomToken(16);
      destPath = path.join(this.cfg.fileStoreDir, fileId);
      dest = fs.createWriteStream(destPath, { mode: 0o600 });

      file.on('data', (chunk) => {
        written += chunk.length;
        if (written > maxBytes) {
          failed = true;
          file.resume();
        }
      });

      file.pipe(dest);
    });

    busboy.on('error', () => {
      failed = true;
      if (destPath) fs.unlink(destPath, () => {});
      if (!res.headersSent) {
        res.writeHead(413);
        res.end('payload too large or invalid multipart');
      }
    });

    busboy.on('finish', () => {
      if (failed || !fileId || !dest) {
        if (destPath) fs.unlink(destPath, () => {});
        if (!res.headersSent) {
          res.writeHead(400);
          res.end('missing file field');
        }
        return;
      }

      const entry = {
        id: fileId,
        name,
        mime: mimeType,
        sizeBytes: written,
        path: destPath,
        downloadTok: dlTok,
        expiresAt: Date.now() + this.cfg.fileTtlMs,
        maxDownloads: this.cfg.fileMaxDownloads || 10,
        downloads: 0,
      };
      this.store.files.set(fileId, entry);

      const body = {
        file_id: fileId,
        name,
        size_bytes: written,
        mime: mimeType,
        download_path: `/files/${fileId}?token=${dlTok}`,
      };
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(body));
    });

    req.pipe(busboy);
  }

  /** @param {import('node:http').IncomingMessage} req @param {import('node:http').ServerResponse} res @param {string} fileId */
  handleDownload(req, res, fileId) {
    const f = this.store.files.get(fileId);
    if (!f || Date.now() > f.expiresAt) {
      res.writeHead(404);
      res.end('not found');
      return;
    }
    if (!this.downloadAuthOK(req, f)) {
      res.writeHead(401);
      res.end('unauthorized');
      return;
    }
    if (f.downloads >= f.maxDownloads) {
      res.writeHead(410);
      res.end('download limit exceeded');
      return;
    }
    f.downloads += 1;
    res.writeHead(200, {
      'Content-Type': f.mime,
      'Content-Disposition': `attachment; filename="${f.name}"`,
    });
    fs.createReadStream(f.path).pipe(res);
  }
}

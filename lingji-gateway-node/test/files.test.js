import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createServer } from '../src/server.js';

function multipartBody(name, content) {
  const boundary = '----lingji-test';
  const body = [
    `--${boundary}`,
    `Content-Disposition: form-data; name="file"; filename="${name}"`,
    'Content-Type: text/plain',
    '',
    content,
    `--${boundary}--`,
    '',
  ].join('\r\n');
  return { boundary, body };
}

function httpRequest(options, body) {
  return new Promise((resolve, reject) => {
    const req = http.request(options, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        resolve({
          status: res.statusCode,
          body: Buffer.concat(chunks).toString('utf8'),
        });
      });
    });
    req.on('error', reject);
    if (body) req.end(body);
    else req.end();
  });
}

test('files upload unauthorized', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'lingji-node-files-'));
  const app = createServer({
    port: 0,
    authToken: 'test-token',
    fileStoreDir: dir,
  });
  const port = await app.listen(0);
  const { boundary, body } = multipartBody('x.txt', 'x');
  const res = await httpRequest(
    {
      hostname: '127.0.0.1',
      port,
      method: 'POST',
      path: '/files',
      headers: {
        'Content-Type': `multipart/form-data; boundary=${boundary}`,
        'Content-Length': Buffer.byteLength(body),
      },
    },
    body,
  );
  assert.equal(res.status, 401);
  await app.close();
  fs.rmSync(dir, { recursive: true, force: true });
});

test('files upload and download', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'lingji-node-files-'));
  const app = createServer({
    port: 0,
    authToken: 'test-token',
    fileStoreDir: dir,
    fileMaxDownloads: 3,
  });
  const port = await app.listen(0);
  const { boundary, body } = multipartBody('hello.txt', 'hello g6');
  const up = await httpRequest(
    {
      hostname: '127.0.0.1',
      port,
      method: 'POST',
      path: '/files',
      headers: {
        'Content-Type': `multipart/form-data; boundary=${boundary}`,
        Authorization: 'Bearer test-token',
        'Content-Length': Buffer.byteLength(body),
      },
    },
    body,
  );
  assert.equal(up.status, 200);
  assert.match(up.body, /download_path/);
  const parsed = JSON.parse(up.body);
  const dl = await httpRequest({
    hostname: '127.0.0.1',
    port,
    method: 'GET',
    path: parsed.download_path,
  });
  assert.equal(dl.status, 200);
  assert.equal(dl.body, 'hello g6');
  await app.close();
  fs.rmSync(dir, { recursive: true, force: true });
});

test('health returns node runtime', async () => {
  const app = createServer({ port: 0, authToken: '' });
  const port = await app.listen(0);
  const res = await httpRequest({
    hostname: '127.0.0.1',
    port,
    method: 'GET',
    path: '/health',
  });
  assert.equal(res.status, 200);
  const json = JSON.parse(res.body);
  assert.equal(json.status, 'ok');
  assert.equal(json.runtime, 'node');
  await app.close();
});

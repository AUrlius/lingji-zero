import test from 'node:test';
import assert from 'node:assert/strict';
import { Hub, Client } from '../src/hub/hub.js';

function mockWs() {
  /** @type {string[]} */
  const sent = [];
  return {
    readyState: 1,
    bufferedAmount: 0,
    sent,
    send(data) {
      sent.push(String(data));
    },
    close() {},
  };
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

test('hub register unregister send', async () => {
  const hub = new Hub(30000);
  const ws = mockWs();
  const c = new Client('target', ws, hub);
  hub.register(c);

  assert.equal(hub.len(), 1);
  assert.ok(hub.sendToDevice('target', 'hello'));
  assert.equal(ws.sent[0], 'hello');
  assert.equal(hub.sendToDevice('nobody', 'x'), false);

  hub.unregister(c);
  assert.equal(hub.len(), 0);
  hub.stop();
});

test('hub replace duplicate device', async () => {
  const hub = new Hub(30000);
  const ws1 = mockWs();
  const ws2 = mockWs();
  hub.register(new Client('dup', ws1, hub));
  hub.register(new Client('dup', ws2, hub));
  await sleep(5);
  assert.equal(hub.len(), 1);
  hub.stop();
});

test('hub broadcast exclude', () => {
  const hub = new Hub(30000);
  const wsA = mockWs();
  const wsB = mockWs();
  hub.register(new Client('a', wsA, hub));
  hub.register(new Client('b', wsB, hub));
  hub.broadcastToAll('secret', 'a');
  assert.equal(wsA.sent.length, 0);
  assert.equal(wsB.sent.length, 1);
  hub.stop();
});

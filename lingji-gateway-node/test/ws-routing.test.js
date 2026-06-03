import test from 'node:test';
import assert from 'node:assert/strict';
import { Hub, Client } from '../src/hub/hub.js';
import { OfflineQueue } from '../src/queue/offline.js';
import { WSHandler } from '../src/handler/ws.js';
import { MsgType, newMessage, toJSON } from '../src/protocol/message.js';

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

test('deliverDownstream targeted', () => {
  const hub = new Hub(120000);
  const queue = new OfflineQueue(16);
  const ws = new WSHandler(hub, { authToken: '', maxMessageSize: 65536 }, queue);

  const phoneA = new Client('phone-a', mockWs(), hub);
  const phoneB = new Client('phone-b', mockWs(), hub);
  hub.register(phoneA);
  hub.register(phoneB);

  const msg = newMessage(MsgType.AGENT_RES, 'lingji-pc', {
    text: 'hello a',
    target_device_id: 'phone-a',
  });
  const raw = toJSON(msg);
  ws.deliverDownstream(raw);

  assert.equal(phoneA.ws.sent.length, 1);
  assert.equal(phoneA.ws.sent[0], raw);
  assert.equal(phoneB.ws.sent.length, 0);
  hub.stop();
});

test('deliverDownstream offline queue', () => {
  const hub = new Hub(120000);
  const queue = new OfflineQueue(16);
  const ws = new WSHandler(hub, { authToken: '', maxMessageSize: 65536 }, queue);

  const msg = newMessage(MsgType.AGENT_RES, 'lingji-pc', {
    text: 'queued',
    target_device_id: 'phone-offline',
  });
  const raw = toJSON(msg);
  ws.deliverDownstream(raw);

  const queued = queue.dequeueAll('phone-offline');
  assert.equal(queued.length, 1);
  assert.equal(queued[0], raw);
  hub.stop();
});

test('deliverDownstream broadcast fallback', () => {
  const hub = new Hub(120000);
  const queue = new OfflineQueue(16);
  const ws = new WSHandler(hub, { authToken: '', maxMessageSize: 65536 }, queue);

  const phoneA = new Client('phone-a', mockWs(), hub);
  const phoneB = new Client('phone-b', mockWs(), hub);
  hub.register(phoneA);
  hub.register(phoneB);

  const msg = newMessage(MsgType.AGENT_RES, 'lingji-pc', { text: 'broadcast all' });
  const raw = toJSON(msg);
  ws.deliverDownstream(raw);

  assert.equal(phoneA.ws.sent.length, 1);
  assert.equal(phoneB.ws.sent.length, 1);
  hub.stop();
});

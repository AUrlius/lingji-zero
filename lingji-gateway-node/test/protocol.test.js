import test from 'node:test';
import assert from 'node:assert/strict';
import { MsgType, newMessage, parseMessage, toJSON } from '../src/protocol/message.js';

test('newMessage serializes golden fields', () => {
  const msg = newMessage(MsgType.AGENT_RES, 'lingji-pc', {
    text: 'hello from node',
    status: 'success',
  });
  msg.msg_id = 'node-interop-001';
  msg.timestamp = 1717000001.456;

  const raw = toJSON(msg);
  const parsed = parseMessage(raw);
  assert.equal(parsed.msg_id, 'node-interop-001');
  assert.equal(parsed.msg_type, MsgType.AGENT_RES);
  assert.equal(parsed.device_id, 'lingji-pc');
  assert.equal(parsed.timestamp, 1717000001.456);
  assert.equal(parsed.payload.text, 'hello from node');
});

test('parse Python-style interop JSON', () => {
  const raw = JSON.stringify({
    msg_id: 'interop-test-001',
    msg_type: 'CMD_TEXT',
    device_id: 'phone-001',
    timestamp: 1717000000.123,
    payload: { text: 'hello from python', seq: 42 },
  });
  const msg = parseMessage(raw);
  assert.equal(msg.msg_id, 'interop-test-001');
  assert.equal(msg.msg_type, 'CMD_TEXT');
  assert.equal(msg.payload.text, 'hello from python');
  assert.equal(msg.payload.seq, 42);
});

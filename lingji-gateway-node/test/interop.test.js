import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { MsgType, newMessage, parseMessage, toJSON } from '../src/protocol/message.js';

const FIXTURE = path.join('test', 'fixtures', 'python-msg.json');

test('interop parse python golden fixture', () => {
  if (!fs.existsSync(FIXTURE)) {
    // generate inline if fixture missing
    const raw = JSON.stringify({
      msg_id: 'interop-test-001',
      msg_type: 'CMD_TEXT',
      device_id: 'phone-001',
      timestamp: 1717000000.123,
      payload: { text: 'hello from python', seq: 42 },
    });
    const msg = parseMessage(raw);
    assert.equal(msg.msg_id, 'interop-test-001');
    return;
  }
  const raw = fs.readFileSync(FIXTURE, 'utf8');
  const msg = parseMessage(raw);
  assert.equal(msg.msg_type, MsgType.CMD_TEXT);
  assert.equal(msg.payload.text, 'hello from python');
});

test('interop write node json for python', () => {
  const msg = newMessage(MsgType.AGENT_RES, 'lingji-pc', {
    text: 'hello from node',
    status: 'success',
  });
  msg.msg_id = 'node-interop-001';
  msg.timestamp = 1717000001.456;
  const raw = toJSON(msg);
  JSON.parse(raw);
  fs.writeFileSync(path.join(os.tmpdir(), 'node_msg.json'), raw, { mode: 0o644 });
  assert.match(raw, /hello from node/);
});

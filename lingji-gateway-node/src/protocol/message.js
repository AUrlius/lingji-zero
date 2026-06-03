import { randomUUID } from 'node:crypto';

/** @enum {string} */
export const MsgType = {
  AUTH_REQ: 'AUTH_REQ',
  HEARTBEAT: 'HEARTBEAT',
  CMD_TEXT: 'CMD_TEXT',
  CMD_LIST_SESSIONS: 'CMD_LIST_SESSIONS',
  HITL_REQ: 'HITL_REQ',
  HITL_RES: 'HITL_RES',
  AGENT_RES: 'AGENT_RES',
};

/**
 * @param {string} msgType
 * @param {string} deviceId
 * @param {Record<string, unknown>} [payload]
 */
export function newMessage(msgType, deviceId, payload = {}) {
  return {
    msg_id: randomUUID(),
    msg_type: msgType,
    device_id: deviceId,
    timestamp: Date.now() / 1000,
    payload: payload ?? {},
  };
}

/** @param {string} raw */
export function parseMessage(raw) {
  return JSON.parse(raw);
}

/** @param {object} msg */
export function toJSON(msg) {
  return JSON.stringify(msg);
}

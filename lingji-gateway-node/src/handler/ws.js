import { WebSocketServer } from 'ws';
import { Client, Hub } from '../hub/hub.js';
import { OfflineQueue } from '../queue/offline.js';
import { MsgType, newMessage, parseMessage, toJSON } from '../protocol/message.js';
import { DEFAULT_AGENT_ID, isAgentDevice, resolveTargetAgentID } from './routing.js';

export class WSHandler {
  /**
   * @param {Hub} hub
   * @param {import('../config.js').GatewayConfig} cfg
   * @param {OfflineQueue} queue
   */
  constructor(hub, cfg, queue) {
    this.hub = hub;
    this.cfg = cfg;
    this.queue = queue;
  }

  /** @param {import('node:http').IncomingMessage} req */
  authOK(req) {
    if (!this.cfg.authToken) return true;
    const auth = req.headers.authorization;
    if (auth === `Bearer ${this.cfg.authToken}`) return true;
    const url = new URL(req.url, 'http://localhost');
    return url.searchParams.get('token') === this.cfg.authToken;
  }

  /** @param {import('node:http').Server} server */
  attach(server) {
    this.wss = new WebSocketServer({
      server,
      path: '/ws',
      maxPayload: this.cfg.maxMessageSize,
    });

    this.wss.on('connection', (ws, req) => {
      if (!this.authOK(req)) {
        ws.close(4401, 'unauthorized');
        return;
      }

      const remote = req.socket.remoteAddress ?? 'unknown';
      const client = new Client(`pending-${remote}`, ws, this.hub);
      this.hub.register(client);

      const pingTimer = setInterval(() => {
        if (ws.readyState === 1) ws.ping();
      }, 10000);

      ws.on('pong', () => client.updateHeartbeat());

      ws.on('message', (raw) => {
        const text = raw.toString();
        let msg;
        try {
          msg = parseMessage(text);
        } catch {
          return;
        }

        client.updateHeartbeat();

        if (msg.msg_type === MsgType.AUTH_REQ) {
          this.handleAuth(client, msg);
          return;
        }

        if (msg.msg_type === MsgType.HEARTBEAT) {
          return;
        }

        this.routeMessage(msg.msg_type, msg.device_id, text);
      });

      ws.on('close', () => {
        clearInterval(pingTimer);
        this.hub.unregister(client);
      });
    });
  }

  /** @param {Client} client @param {object} msg */
  handleAuth(client, msg) {
    if (this.cfg.authToken) {
      const clientToken = msg.payload?.token;
      if (clientToken !== this.cfg.authToken) {
        const reply = newMessage(MsgType.AGENT_RES, 'gateway', {
          text: 'auth_failed',
          status: 'rejected',
        });
        client.trySend(toJSON(reply));
        setTimeout(() => client.closeSend(), 500);
        return;
      }
    }

    const newId = msg.payload?.device_id;
    if (typeof newId === 'string' && newId) {
      const oldId = client.deviceId;
      client.deviceId = newId;
      this.hub.reRegister(client, oldId);
      this.deliverOfflineMessages(newId, client);

      const reply = newMessage(MsgType.AGENT_RES, 'gateway', {
        text: 'auth_ok',
        status: 'connected',
      });
      client.trySend(toJSON(reply));
    }
  }

  /** @param {string} msgType @param {string} fromDevice @param {string} raw */
  routeMessage(msgType, fromDevice, raw) {
    switch (msgType) {
      case MsgType.CMD_TEXT:
      case MsgType.CMD_LIST_SESSIONS: {
        const pcID = resolveTargetAgentID(raw);
        if (!this.hub.sendToDevice(pcID, raw)) {
          this.queue.enqueue(pcID, raw);
          this.notifyDelayed(fromDevice, pcID);
        }
        break;
      }
      case MsgType.AGENT_RES:
      case MsgType.HITL_REQ:
        this.deliverDownstream(raw);
        break;
      case MsgType.HITL_RES: {
        const pcID = resolveTargetAgentID(raw);
        if (!this.hub.sendToDevice(pcID, raw)) {
          this.queue.enqueue(pcID, raw);
        }
        break;
      }
      default:
        break;
    }
  }

  /** @param {string} deviceId @param {Client} client */
  deliverOfflineMessages(deviceId, client) {
    const msgs = this.queue.dequeueAll(deviceId);
    for (const msg of msgs) {
      if (!client.trySend(msg)) break;
    }
  }

  /** @param {string} toDevice @param {string} agentId */
  notifyDelayed(toDevice, agentId) {
    const reply = newMessage(MsgType.AGENT_RES, 'gateway', {
      text: `PC (${agentId}) 当前不在线，消息已缓存，上线后将自动投递。`,
      status: 'queued',
      target_device_id: toDevice,
      target_agent_id: agentId,
    });
    this.hub.sendToDevice(toDevice, toJSON(reply));
  }

  /** @param {string} raw */
  deliverDownstream(raw) {
    let msg;
    try {
      msg = parseMessage(raw);
    } catch {
      this.hub.broadcastToAll(raw, 'lingji-pc');
      return;
    }

    const target = msg.payload?.target_device_id;
    if (typeof target === 'string' && target && target !== 'lingji-pc') {
      if (this.hub.sendToDevice(target, raw)) return;
      this.queue.enqueue(target, raw);
      return;
    }

    this.hub.broadcastToAll(raw, 'lingji-pc');
  }
}

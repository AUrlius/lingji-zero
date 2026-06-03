export class Client {
  /**
   * @param {string} deviceId
   * @param {import('ws').WebSocket} ws
   * @param {Hub} hub
   */
  constructor(deviceId, ws, hub) {
    this.deviceId = deviceId;
    this.ws = ws;
    this.hub = hub;
    this.lastBeat = Date.now();
    /** @type {string[]} */
    this.sendQueue = [];
    this.closed = false;
  }

  updateHeartbeat() {
    this.lastBeat = Date.now();
  }

  /** @param {string|Buffer} data */
  trySend(data) {
    if (this.closed || this.ws.readyState !== 1) return false;
    if (this.ws.bufferedAmount > 0) {
      if (this.sendQueue.length >= 64) return false;
      this.sendQueue.push(typeof data === 'string' ? data : data.toString());
      return true;
    }
    this.ws.send(data);
    this.flushQueue();
    return true;
  }

  flushQueue() {
    while (this.sendQueue.length > 0 && this.ws.bufferedAmount === 0) {
      const next = this.sendQueue.shift();
      if (next) this.ws.send(next);
    }
  }

  closeSend() {
    this.closed = true;
    this.sendQueue.length = 0;
    try {
      this.ws.close();
    } catch {
      /* ignore */
    }
  }
}

export class Hub {
  /** @param {number} heartbeatTimeoutMs */
  constructor(heartbeatTimeoutMs) {
    this.heartbeatTimeoutMs = heartbeatTimeoutMs;
    /** @type {Map<string, Client>} */
    this.clients = new Map();
    this._stopped = false;
    this._heartbeatTimer = setInterval(
      () => this.checkHeartbeats(),
      Math.max(1000, heartbeatTimeoutMs / 2),
    );
  }

  stop() {
    if (this._stopped) return;
    this._stopped = true;
    clearInterval(this._heartbeatTimer);
    for (const c of this.clients.values()) {
      c.closeSend();
    }
    this.clients.clear();
  }

  /** @param {Client} client */
  register(client) {
    const old = this.clients.get(client.deviceId);
    if (old && old !== client) {
      old.closeSend();
    }
    this.clients.set(client.deviceId, client);
  }

  /** @param {Client} client @param {string} oldDeviceId */
  reRegister(client, oldDeviceId) {
    this.clients.delete(oldDeviceId);
    const old = this.clients.get(client.deviceId);
    if (old && old !== client) {
      old.closeSend();
    }
    this.clients.set(client.deviceId, client);
  }

  /** @param {Client} client */
  unregister(client) {
    const cur = this.clients.get(client.deviceId);
    if (cur === client) {
      this.clients.delete(client.deviceId);
    }
  }

  len() {
    return this.clients.size;
  }

  /** @param {string} deviceId */
  getClient(deviceId) {
    return this.clients.get(deviceId) ?? null;
  }

  /** @param {string} deviceId @param {string} data */
  sendToDevice(deviceId, data) {
    const c = this.clients.get(deviceId);
    if (!c) return false;
    if (!c.trySend(data)) {
      this.unregister(c);
      return false;
    }
    return true;
  }

  /** @param {string} data @param {string} [excludeDevice] */
  broadcastToAll(data, excludeDevice = '') {
    for (const [id, c] of this.clients) {
      if (id === excludeDevice) continue;
      c.trySend(data);
    }
  }

  checkHeartbeats() {
    const now = Date.now();
    for (const c of this.clients.values()) {
      if (now - c.lastBeat > this.heartbeatTimeoutMs) {
        this.unregister(c);
        c.closeSend();
      }
    }
  }

  onlineDevices() {
    return [...this.clients.keys()];
  }
}

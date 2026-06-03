class RingBuffer {
  /** @param {number} maxSize */
  constructor(maxSize) {
    this.data = new Array(maxSize);
    this.head = 0;
    this.tail = 0;
    this.size = 0;
    this.maxSize = maxSize;
  }

  /** @param {string} msg */
  enqueue(msg) {
    if (this.size === this.maxSize) {
      this.head = (this.head + 1) % this.maxSize;
      this.size -= 1;
    }
    this.data[this.tail] = msg;
    this.tail = (this.tail + 1) % this.maxSize;
    this.size += 1;
  }

  /** @returns {string[]} */
  dequeueAll() {
    if (this.size === 0) return [];
    const result = [];
    for (let i = 0; i < this.size; i += 1) {
      const idx = (this.head + i) % this.maxSize;
      result.push(this.data[idx]);
    }
    this.head = 0;
    this.tail = 0;
    this.size = 0;
    return result;
  }

  len() {
    return this.size;
  }
}

export class OfflineQueue {
  /** @param {number} maxSize */
  constructor(maxSize) {
    this.maxSize = maxSize;
    /** @type {Map<string, RingBuffer>} */
    this.buffers = new Map();
  }

  /** @param {string} deviceId @param {string} msg */
  enqueue(deviceId, msg) {
    let buf = this.buffers.get(deviceId);
    if (!buf) {
      buf = new RingBuffer(this.maxSize);
      this.buffers.set(deviceId, buf);
    }
    buf.enqueue(msg);
  }

  /** @param {string} deviceId @returns {string[]} */
  dequeueAll(deviceId) {
    const buf = this.buffers.get(deviceId);
    if (!buf) return [];
    return buf.dequeueAll();
  }

  /** @param {string} deviceId */
  len(deviceId) {
    const buf = this.buffers.get(deviceId);
    return buf ? buf.len() : 0;
  }
}

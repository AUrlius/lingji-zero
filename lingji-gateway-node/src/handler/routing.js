const DEFAULT_AGENT_ID = 'lingji-pc';

export function isAgentDevice(deviceId) {
  return typeof deviceId === 'string' && deviceId.startsWith('lingji-');
}

/** @param {string} raw */
export function resolveTargetAgentID(raw) {
  try {
    const msg = JSON.parse(raw);
    const id = msg.payload?.target_agent_id;
    if (typeof id === 'string' && id) return id;
  } catch {
    /* ignore */
  }
  return DEFAULT_AGENT_ID;
}

export { DEFAULT_AGENT_ID };

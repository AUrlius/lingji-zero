/** 灵机 G6.4 — WS / Files / 会话（window.LingjiChat） */
(function () {
  'use strict';

  var UI = function () { return window.LingjiUI; };

  var CACHE_SESSIONS = 'lingji_sessions_v1';
  var CACHE_ACTIVE = 'lingji_active_thread';
  var CACHE_HITL_QUEUE = 'lingji_hitl_res_queue_v1';
  var CACHE_TARGET_AGENT = 'lingji_target_agent_id';

  var DEFAULT_AGENT_ID = 'lingji-pc';
  var AGENT_LABELS = {
    'lingji-pc': 'Primary PC',
    'lingji-laptop': 'Laptop',
  };

  var DEVICE_ID = (function () {
    var key = 'lingji_device_id';
    var id = localStorage.getItem(key);
    if (!id) {
      id = 'phone-' + Math.random().toString(36).slice(2, 8);
      localStorage.setItem(key, id);
    }
    return id;
  })();

  var GATEWAY_TOKEN = (function () {
    var fromUrl = new URLSearchParams(location.search).get('token');
    if (fromUrl) {
      try { localStorage.setItem('lingji_gateway_token', fromUrl); } catch (e) {}
      return fromUrl;
    }
    try { return localStorage.getItem('lingji_gateway_token') || ''; } catch (e) { return ''; }
  })();
  var DEBUG_UI = new URLSearchParams(location.search).has('debug');

  var ws = null;
  var msgId = 0;
  var heartbeatTimer = null;
  var authenticated = false;
  var pendingNewSession = false;
  var activeThreadId = null;
  var sessions = [];
  var pendingUploads = [];
  var switchingSession = false;
  var lastSessionListSig = '';
  var switchSessionTimer = null;
  var pendingSwitchThreadId = null;
  var onlineAgents = [];
  var selectedAgentId = localStorage.getItem(CACHE_TARGET_AGENT) || DEFAULT_AGENT_ID;

  function el(id) {
    return document.getElementById(id);
  }

  function isOnline() {
    return ws && ws.readyState === WebSocket.OPEN && authenticated;
  }

  function historyCacheKey(threadId) {
    return 'lingji_history_' + threadId;
  }

  function saveSessionsCache() {
    try {
      sessionStorage.setItem(CACHE_SESSIONS, JSON.stringify(sessions));
      if (activeThreadId) {
        sessionStorage.setItem(CACHE_ACTIVE, activeThreadId);
      }
    } catch (e) {}
  }

  function loadSessionsCache() {
    try {
      var raw = sessionStorage.getItem(CACHE_SESSIONS);
      if (!raw) return false;
      sessions = JSON.parse(raw);
      activeThreadId = sessionStorage.getItem(CACHE_ACTIVE) || null;
      return sessions.length > 0;
    } catch (e) {
      return false;
    }
  }

  function saveHistoryCache(threadId, history) {
    if (!threadId || !Array.isArray(history)) return;
    try {
      sessionStorage.setItem(historyCacheKey(threadId), JSON.stringify(history));
    } catch (e) {}
  }

  function loadHistoryCache(threadId) {
    if (!threadId) return null;
    try {
      var raw = sessionStorage.getItem(historyCacheKey(threadId));
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }

  function restoreFromCache() {
    if (!loadSessionsCache()) return;
    renderSessionList(true);
    if (activeThreadId) {
      var history = loadHistoryCache(activeThreadId);
      if (history && history.length) {
        UI().renderHistory(history);
      }
    }
  }

  function loadHitlResQueue() {
    try {
      var raw = sessionStorage.getItem(CACHE_HITL_QUEUE);
      return raw ? JSON.parse(raw) : [];
    } catch (e) {
      return [];
    }
  }

  function saveHitlResQueue(queue) {
    try {
      if (!queue.length) {
        sessionStorage.removeItem(CACHE_HITL_QUEUE);
      } else {
        sessionStorage.setItem(CACHE_HITL_QUEUE, JSON.stringify(queue));
      }
    } catch (e) {}
  }

  function enqueueHitlRes(taskId, decision) {
    var queue = loadHitlResQueue().filter(function (item) {
      return item.task_id !== taskId;
    });
    queue.push({
      task_id: taskId,
      decision: decision,
      target_agent_id: getSelectedAgentId(),
      ts: Date.now(),
    });
    saveHitlResQueue(queue);
  }

  function flushHitlResQueue() {
    if (!isOnline()) return;
    var queue = loadHitlResQueue();
    if (!queue.length) return;
    queue.forEach(function (item) {
      ws.send(JSON.stringify({
        msg_id: 'hitl-q-' + (++msgId),
        msg_type: 'HITL_RES',
        device_id: DEVICE_ID,
        timestamp: Date.now() / 1000,
        payload: withTargetAgent({
          task_id: item.task_id,
          decision: item.decision,
          target_agent_id: item.target_agent_id || getSelectedAgentId(),
        }),
      }));
    });
    saveHitlResQueue([]);
    UI().appendSystem('已提交离线期间的审批，等待 Agent 处理…');
  }

  function agentLabel(id) {
    return AGENT_LABELS[id] || id;
  }

  function getSelectedAgentId() {
    return selectedAgentId || DEFAULT_AGENT_ID;
  }

  function saveSelectedAgentId(id) {
    selectedAgentId = id || DEFAULT_AGENT_ID;
    try {
      localStorage.setItem(CACHE_TARGET_AGENT, selectedAgentId);
    } catch (e) {}
  }

  function withTargetAgent(payload) {
    var out = payload || {};
    if (!out.target_agent_id) {
      out.target_agent_id = getSelectedAgentId();
    }
    return out;
  }

  function renderAgentSelect() {
    var select = el('agentSelect');
    if (!select) return;
    var known = {};
    onlineAgents.forEach(function (a) {
      known[a.device_id] = true;
    });
    if (!known[getSelectedAgentId()]) {
      onlineAgents = onlineAgents.concat([{ device_id: getSelectedAgentId() }]);
    }
    select.innerHTML = '';
    onlineAgents.forEach(function (a) {
      var opt = document.createElement('option');
      opt.value = a.device_id;
      opt.textContent = agentLabel(a.device_id);
      select.appendChild(opt);
    });
    select.value = getSelectedAgentId();
    select.disabled = !isOnline();
  }

  async function refreshOnlineAgents() {
    try {
      var base = getApiBase();
      var url = base + '/v1/agents?token=' + encodeURIComponent(GATEWAY_TOKEN);
      var resp = await fetch(url, {
        headers: { Authorization: 'Bearer ' + GATEWAY_TOKEN },
      });
      if (!resp.ok) return;
      var data = await resp.json();
      onlineAgents = Array.isArray(data.agents) ? data.agents : [];
      if (data.default_agent_id && !localStorage.getItem(CACHE_TARGET_AGENT)) {
        saveSelectedAgentId(data.default_agent_id);
      }
      renderAgentSelect();
    } catch (e) {}
  }

  function getApiBase() {
    var host = el('gwHost').value || '127.0.0.1';
    var port = el('gwPort').value || '8765';
    var scheme = (port === '443') ? 'https' : 'http';
    if (port === '443' || port === '80') return scheme + '://' + host;
    return scheme + '://' + host + ':' + port;
  }

  function isForThisDevice(payload) {
    if (!payload) return true;
    var target = payload.target_device_id;
    if (!target) return true;
    return target === DEVICE_ID;
  }

  function finishSessionSwitch() {
    switchingSession = false;
    UI().setComposerDisabled(false);
    if (switchSessionTimer) {
      clearTimeout(switchSessionTimer);
      switchSessionTimer = null;
    }
  }

  function setSwitchingSession(on) {
    switchingSession = on;
    UI().setComposerDisabled(on);
  }

  function applySessionPayload(p) {
    if (p.sessions) {
      sessions = p.sessions;
      if (p.thread_id) activeThreadId = p.thread_id;
      else {
        var active = sessions.find(function (s) { return s.active; });
        if (active) activeThreadId = active.thread_id;
      }
      saveSessionsCache();
      renderSessionList();
    }
    if (Array.isArray(p.history) && activeThreadId) {
      saveHistoryCache(activeThreadId, p.history);
      UI().renderHistory(p.history);
    }
    if (p.pending_hitl) {
      showHitlRequest(p.pending_hitl);
    }
    if (p.status === 'session_switched' && p.text) {
      UI().appendSystem(p.text);
    }
    finishSessionSwitch();
    pendingSwitchThreadId = null;
  }

  function renderSessionList(force) {
    var sig = sessions.map(function (s) {
      return s.thread_id + ':' + (s.title || '') + ':' + (s.active ? '1' : '0');
    }).join('|');
    if (!force && sig === lastSessionListSig) {
      UI().updateSessionActiveClass(sessions, activeThreadId);
      return;
    }
    lastSessionListSig = sig;
    UI().renderSessionList(sessions, activeThreadId, switchSession);
  }

  function requestSessionList() {
    if (!isOnline()) return;
    ws.send(JSON.stringify({
      msg_id: 'list-' + (++msgId),
      msg_type: 'CMD_LIST_SESSIONS',
      device_id: DEVICE_ID,
      timestamp: Date.now() / 1000,
      payload: withTargetAgent({}),
    }));
  }

  function sendSessionSwitch(threadId) {
    ws.send(JSON.stringify({
      msg_id: 'sw-' + (++msgId),
      msg_type: 'CMD_TEXT',
      device_id: DEVICE_ID,
      timestamp: Date.now() / 1000,
      payload: withTargetAgent({ thread_id: threadId, text: '' }),
    }));

    if (switchSessionTimer) clearTimeout(switchSessionTimer);
    switchSessionTimer = setTimeout(function () {
      if (switchingSession) {
        finishSessionSwitch();
        UI().appendSystem('加载会话超时，请重试');
      }
    }, 15000);
  }

  function switchSessionLocal(threadId, message) {
    activeThreadId = threadId;
    pendingNewSession = false;
    saveSessionsCache();
    UI().clearChat();
    var history = loadHistoryCache(threadId);
    if (history && history.length) {
      UI().renderHistory(history);
      UI().appendSystem(message || '离线浏览缓存，连接恢复后将同步');
    } else {
      UI().appendSystem(message || '未连接，无法加载会话');
    }
    UI().updateSessionActiveClass(sessions, activeThreadId);
    UI().closeSidebar();
  }

  function switchSession(threadId) {
    if (!threadId || threadId === activeThreadId) {
      UI().closeSidebar();
      return;
    }
    if (switchingSession) return;

    if (!isOnline()) {
      pendingSwitchThreadId = threadId;
      switchSessionLocal(threadId);
      return;
    }

    activeThreadId = threadId;
    pendingNewSession = false;
    setSwitchingSession(true);
    UI().clearChat();
    UI().appendSystem('正在加载会话…');
    UI().updateSessionActiveClass(sessions, activeThreadId);
    sendSessionSwitch(threadId);
    UI().closeSidebar();
  }

  function onConnected() {
    refreshOnlineAgents();
    flushHitlResQueue();
    if (pendingSwitchThreadId) {
      var tid = pendingSwitchThreadId;
      pendingSwitchThreadId = null;
      activeThreadId = tid;
      setSwitchingSession(true);
      UI().clearChat();
      UI().appendSystem('正在加载会话…');
      sendSessionSwitch(tid);
      return;
    }
    requestSessionList();
  }

  function startNewSession() {
    pendingNewSession = true;
    activeThreadId = null;
    pendingUploads = [];
    refreshPendingUploads();
    UI().clearChat();
    UI().appendSystem('已开始新对话');
    UI().closeSidebar();
    UI().focusInput();
    try {
      sessionStorage.removeItem(CACHE_ACTIVE);
    } catch (e) {}
  }

  function refreshPendingUploads() {
    UI().renderPendingUploads(pendingUploads, function (idx) {
      pendingUploads.splice(idx, 1);
      refreshPendingUploads();
    });
  }

  async function uploadFilesToGateway(files) {
    var base = getApiBase();
    var tasks = Array.from(files).map(async function (file) {
      var form = new FormData();
      form.append('file', file, file.name);
      var resp = await fetch(base + '/files?token=' + encodeURIComponent(GATEWAY_TOKEN), {
        method: 'POST',
        headers: { Authorization: 'Bearer ' + GATEWAY_TOKEN },
        body: form,
      });
      if (!resp.ok) {
        throw new Error(file.name + ': ' + (await resp.text()).slice(0, 80));
      }
      return resp.json();
    });
    return Promise.all(tasks);
  }

  function buildUploadPayload() {
    return pendingUploads
      .filter(function (u) { return u.status === 'ready' && u.file_id; })
      .map(function (u) {
        return {
          file_id: u.file_id,
          name: u.name,
          mime: u.mime,
          size_bytes: u.size_bytes,
          download_path: u.download_path,
        };
      });
  }

  async function ensurePendingUploaded() {
    var need = pendingUploads.filter(function (u) {
      return u.status === 'local' || u.status === 'error';
    });
    if (!need.length) return;
    need.forEach(function (u) { u.status = 'uploading'; });
    refreshPendingUploads();
    try {
      var uploaded = await uploadFilesToGateway(need.map(function (u) { return u.file; }));
      uploaded.forEach(function (meta, i) {
        var item = need[i];
        item.status = 'ready';
        item.file_id = meta.file_id;
        item.name = meta.name || item.name;
        item.mime = meta.mime;
        item.size_bytes = meta.size_bytes;
        item.download_path = meta.download_path;
        delete item.file;
      });
    } catch (err) {
      need.forEach(function (u) { u.status = 'error'; u.error = err.message; });
      refreshPendingUploads();
      throw err;
    }
    refreshPendingUploads();
  }

  function showHitlRequest(payload) {
    UI().showHitlCard(payload, function (taskId, decision) {
      if (!taskId) {
        UI().appendSystem('审批失败：缺少 task_id');
        return;
      }
      if (!isOnline()) {
        enqueueHitlRes(taskId, decision);
        UI().appendSystem(
          decision === 'approved'
            ? '已记录批准，连接恢复后将自动提交'
            : '已记录拒绝，连接恢复后将自动提交'
        );
        return;
      }
      ws.send(JSON.stringify({
        msg_id: 'hitl-' + (++msgId),
        msg_type: 'HITL_RES',
        device_id: DEVICE_ID,
        timestamp: Date.now() / 1000,
        payload: withTargetAgent({ task_id: taskId, decision: decision }),
      }));
    });
  }

  function handleMessage(msg) {
    if (msg.msg_type === 'AGENT_RES') {
      var p = msg.payload || {};
      if (p.status === 'connected') {
        authenticated = true;
        UI().setConnectionStatus('已连接 (' + DEVICE_ID + ')', true);
        UI().appendSystem('✅ 认证成功');
        onConnected();
        return;
      }
      if (p.status === 'rejected') {
        UI().appendSystem('❌ 认证失败');
        return;
      }
      if (!isForThisDevice(p)) return;
      if (p.status === 'sessions' || p.status === 'session_switched') {
        applySessionPayload(p);
        return;
      }
      if (switchingSession) finishSessionSwitch();
      if (p.status === 'queued') {
        UI().appendMessage('agent', '📦 ' + p.text);
      } else if (p.text || (p.attachments && p.attachments.length)) {
        UI().appendMessage('agent', p.text || '', p.attachments);
      }
    } else if (msg.msg_type === 'HITL_REQ') {
      var hp = msg.payload || {};
      if (!isForThisDevice(hp)) return;
      showHitlRequest(hp);
    }
  }

  function stopHeartbeat() {
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer);
      heartbeatTimer = null;
    }
  }

  function startHeartbeat() {
    stopHeartbeat();
    heartbeatTimer = setInterval(function () {
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      ws.send(JSON.stringify({
        msg_id: 'hb-' + (++msgId),
        msg_type: 'HEARTBEAT',
        device_id: DEVICE_ID,
        timestamp: Date.now() / 1000,
        payload: {},
      }));
    }, 15000);
  }

  async function connect() {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.close();
    }
    stopHeartbeat();
    authenticated = false;

    if (!GATEWAY_TOKEN) {
      UI().setConnectionStatus('未配置 token', false);
      UI().appendSystem('请在 URL 添加 ?token=YOUR_GATEWAY_TOKEN，或先在设置中配置（debug 模式）');
      return;
    }

    var host = el('gwHost').value || '127.0.0.1';
    var port = el('gwPort').value || '8765';
    var scheme = (port === '443') ? 'wss' : 'ws';
    var hostPort = (port === '443' || port === '80') ? host : host + ':' + port;
    var url = scheme + '://' + hostPort + '/ws?token=' + encodeURIComponent(GATEWAY_TOKEN);

    UI().setConnectionStatus('连接中...', false);
    try {
      ws = new WebSocket(url);
      ws.onopen = function () {
        UI().setConnectionStatus('认证中... (' + DEVICE_ID + ')', false);
        ws.send(JSON.stringify({
          msg_id: 'auth-' + (++msgId),
          msg_type: 'AUTH_REQ',
          device_id: DEVICE_ID,
          timestamp: Date.now() / 1000,
          payload: { device_id: DEVICE_ID, token: GATEWAY_TOKEN },
        }));
        startHeartbeat();
      };
      ws.onmessage = function (e) {
        try {
          handleMessage(JSON.parse(e.data));
        } catch (err) {
          UI().appendSystem('消息解析失败: ' + err);
        }
      };
      ws.onclose = function () {
        stopHeartbeat();
        authenticated = false;
        finishSessionSwitch();
        renderAgentSelect();
        UI().setConnectionStatus('已断开', false);
      };
      ws.onerror = function () {
        UI().setConnectionStatus('连接失败', false);
      };
    } catch (e) {
      UI().setConnectionStatus('连接失败: ' + e, false);
    }
  }

  async function send() {
    var text = UI().getInputText();
    if (!text && !pendingUploads.length) return;
    if (switchingSession) return;
    if (!isOnline()) {
      UI().appendSystem('未连接，请等待重连或刷新页面');
      return;
    }
    try {
      if (pendingUploads.some(function (u) { return u.status === 'local' || u.status === 'error'; })) {
        UI().appendSystem('正在上传到 Gateway…');
      }
      await ensurePendingUploaded();
    } catch (err) {
      UI().appendSystem('上传失败: ' + err.message);
      return;
    }
    var uploads = buildUploadPayload();
    pendingUploads = [];
    refreshPendingUploads();
    if (!text && !uploads.length) return;
    UI().appendSystem('已发送，正在保存到电脑…');
    await sendPayload(text, uploads);
    UI().clearInput();
    UI().focusInput();
  }

  async function sendPayload(text, uploads) {
    var payload = { text: text };
    if (uploads && uploads.length) payload.uploads = uploads;
    if (pendingNewSession) {
      payload.new_session = true;
      pendingNewSession = false;
      activeThreadId = null;
    }
    ws.send(JSON.stringify({
      msg_id: 'msg-' + (++msgId),
      msg_type: 'CMD_TEXT',
      device_id: DEVICE_ID,
      timestamp: Date.now() / 1000,
      payload: withTargetAgent(payload),
    }));
    if (text) UI().appendMessage('user', text);
    if (uploads && uploads.length) {
      UI().appendMessage('user', '', uploads);
    }
  }

  function onFilesSelected(fileList) {
    if (!fileList || !fileList.length) return;
    Array.from(fileList).forEach(function (file) {
      pendingUploads.push({
        status: 'local',
        file: file,
        name: file.name || 'file',
      });
    });
    refreshPendingUploads();
    UI().focusInput();
  }

  function init() {
    UI().setupKeyboardViewport();
    UI().setupChatScrollTracking();
    restoreFromCache();
    renderAgentSelect();

    var agentSelect = el('agentSelect');
    if (agentSelect) {
      agentSelect.addEventListener('change', function () {
        saveSelectedAgentId(agentSelect.value);
        if (isOnline()) {
          requestSessionList();
        }
      });
    }

    el('btnNewChat').addEventListener('click', startNewSession);
    el('btnSend').addEventListener('click', send);
    el('fileInput').addEventListener('change', function (e) {
      onFilesSelected(e.target.files);
      e.target.value = '';
    });
    el('input').addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        send();
      }
    });

    if (DEBUG_UI) {
      el('settings').style.display = 'flex';
      el('settings').querySelector('button').addEventListener('click', connect);
    }

    window.addEventListener('pageshow', function (event) {
      if (event.persisted) connect();
    });

    connect();
  }

  window.LingjiChat = {
    init: init,
    connect: connect,
    send: send,
    startNewSession: startNewSession,
    switchSession: switchSession,
  };
})();


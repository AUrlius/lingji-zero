/** 灵机 G6.4 — WS / Files / 会话（window.LingjiChat） */
(function () {
  'use strict';

  var UI = function () { return window.LingjiUI; };

  var STORAGE_CLIENT_ID = 'lingji_client_id';
  var STORAGE_CLIENT_SOURCE = 'lingji_client_id_source';
  var STORAGE_LEGACY_DEVICE = 'lingji_device_id';

  var GATEWAY_TOKEN = (function () {
    var fromUrl = new URLSearchParams(location.search).get('token');
    if (fromUrl) {
      try { localStorage.setItem('lingji_gateway_token', fromUrl); } catch (e) {}
      return fromUrl;
    }
    try { return localStorage.getItem('lingji_gateway_token') || ''; } catch (e) { return ''; }
  })();

  function fnv1aHex8(str) {
    var h = 2166136261;
    for (var i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return ('0000000' + (h >>> 0).toString(16)).slice(-8);
  }

  /** Stable client id: same Gateway token → same id across phone/PC Web (Fleet phase 1). */
  function resolveClientId(token) {
    var fromUrl = new URLSearchParams(location.search).get('client_id');
    if (fromUrl) {
      try {
        localStorage.setItem(STORAGE_CLIENT_ID, fromUrl);
        localStorage.setItem(STORAGE_CLIENT_SOURCE, 'url');
      } catch (e) {}
      return fromUrl;
    }
    try {
      if (localStorage.getItem(STORAGE_CLIENT_SOURCE) === 'url') {
        var custom = localStorage.getItem(STORAGE_CLIENT_ID);
        if (custom) return custom;
      }
    } catch (e) {}
    if (token) {
      var derived = 'user-' + fnv1aHex8(token);
      try {
        localStorage.setItem(STORAGE_CLIENT_ID, derived);
        localStorage.setItem(STORAGE_CLIENT_SOURCE, 'token');
        localStorage.removeItem(STORAGE_LEGACY_DEVICE);
      } catch (e) {}
      return derived;
    }
    try {
      var stored = localStorage.getItem(STORAGE_CLIENT_ID);
      if (stored) return stored;
      var legacy = localStorage.getItem(STORAGE_LEGACY_DEVICE);
      if (legacy) return legacy;
    } catch (e) {}
    var fallback = 'phone-' + Math.random().toString(36).slice(2, 8);
    try { localStorage.setItem(STORAGE_LEGACY_DEVICE, fallback); } catch (e) {}
    return fallback;
  }

  var USER_ID = resolveClientId(GATEWAY_TOKEN);

  var CONNECTION_ID = (function () {
    var key = 'lingji_connection_id';
    try {
      var id = localStorage.getItem(key);
      if (id) return id;
      id = 'conn-' + Math.random().toString(36).slice(2, 10);
      localStorage.setItem(key, id);
      return id;
    } catch (e) {
      return 'conn-' + Math.random().toString(36).slice(2, 10);
    }
  })();

  var CACHE_SESSIONS = 'lingji_sessions_v2_' + USER_ID;
  var CACHE_ACTIVE_PREFIX = 'lingji_active_v3_' + USER_ID + '_';
  var CACHE_HITL_QUEUE = 'lingji_hitl_res_queue_v1_' + USER_ID;
  var CACHE_HITL_PENDING = 'lingji_hitl_pending_v1_' + USER_ID;
  var CACHE_TARGET_AGENT = 'lingji_target_agent_id';

  var DEFAULT_AGENT_ID = 'lingji-pc';
  var AGENT_LABELS = {
    'lingji-pc': '青铜剑',
    'lingji-laptop': '空城记',
  };

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
  var hitlPollTimer = null;
  var activityStaleTimer = null;
  var ACTIVITY_STALE_MS = 90000;

  function el(id) {
    return document.getElementById(id);
  }

  function isOnline() {
    return ws && ws.readyState === WebSocket.OPEN && authenticated;
  }

  function historyCacheKey(threadId, agentId) {
    var aid = agentId || getSelectedAgentId();
    return 'lingji_history_v3_' + USER_ID + '_' + aid + '_' + threadId;
  }

  function activeCacheKey(agentId) {
    return CACHE_ACTIVE_PREFIX + (agentId || getSelectedAgentId());
  }

  function saveActiveThreadForAgent(agentId, threadId) {
    if (!agentId) return;
    try {
      if (threadId) {
        localStorage.setItem(activeCacheKey(agentId), threadId);
      } else {
        localStorage.removeItem(activeCacheKey(agentId));
      }
    } catch (e) {}
  }

  function loadActiveThreadForAgent(agentId) {
    try {
      return localStorage.getItem(activeCacheKey(agentId)) || null;
    } catch (e) {
      return null;
    }
  }

  function mergeHistoryPreferLonger(localHist, serverHist) {
    var local = localHist || [];
    var server = serverHist || [];
    if (server.length > local.length) return server;
    return local;
  }

  function enrichHistoryFromInbox(threadId, agentId, currentHist) {
    if (!threadId || !agentId) return Promise.resolve(currentHist || []);
    return fetchInboxMessages(threadId, agentId).then(function (inboxHist) {
      var merged = mergeHistoryPreferLonger(currentHist, inboxHist);
      if (merged.length) {
        saveHistoryCache(threadId, merged, agentId);
        UI().renderHistory(merged);
      }
      restoreHitlDock();
      return merged;
    });
  }

  function loadHitlPendingList() {
    try {
      var raw = localStorage.getItem(CACHE_HITL_PENDING);
      return raw ? JSON.parse(raw) : [];
    } catch (e) {
      return [];
    }
  }

  function saveHitlPendingList(list) {
    try {
      if (!list || !list.length) {
        localStorage.removeItem(CACHE_HITL_PENDING);
      } else {
        localStorage.setItem(CACHE_HITL_PENDING, JSON.stringify(list));
      }
    } catch (e) {}
  }

  function upsertHitlPending(item) {
    if (!item || !item.task_id) return;
    var list = loadHitlPendingList().filter(function (x) {
      return x.task_id !== item.task_id;
    });
    list.push(item);
    saveHitlPendingList(list);
  }

  function removeHitlPending(taskId) {
    if (!taskId) return;
    var list = loadHitlPendingList().filter(function (x) {
      return x.task_id !== taskId;
    });
    saveHitlPendingList(list);
    var dock = el('hitlDock');
    if (dock) {
      var card = dock.querySelector('.msg.hitl[data-task-id="' + taskId + '"]');
      if (card) card.remove();
      if (!dock.children.length) dock.classList.remove('visible');
    }
  }

  function hitlPayloadWithAgent(payload) {
    var out = Object.assign({}, payload || {});
    if (!out.agent_id) {
      var sess = findSession(activeThreadId);
      out.agent_id = (sess && sess.agent_id) || getSelectedAgentId();
    }
    out.agent_label = agentLabel(out.agent_id);
    return out;
  }

  function restoreHitlDock() {
    var list = loadHitlPendingList();
    if (!list.length) {
      UI().clearHitlDock();
      return;
    }
    UI().clearHitlDock();
    list.forEach(function (item) {
      showHitlRequest(item, true);
    });
  }

  function sendHitlDecision(taskId, decision, agentId) {
    if (!taskId) return;
    var targetAgent = agentId || getSelectedAgentId();
    if (!isOnline()) {
      enqueueHitlRes(taskId, decision, targetAgent);
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
      device_id: CONNECTION_ID,
      timestamp: Date.now() / 1000,
      payload: withTargetAgent({
        task_id: taskId,
        decision: decision,
        target_agent_id: targetAgent,
      }),
    }));
    removeHitlPending(taskId);
  }

  async function fetchHitlPendingFromGateway() {
    if (!GATEWAY_TOKEN || !USER_ID) return;
    var base = getApiBase();
    var url = base + '/v1/hitl/pending?user_id=' + encodeURIComponent(USER_ID)
      + '&token=' + encodeURIComponent(GATEWAY_TOKEN);
    try {
      var resp = await fetch(url, {
        headers: { Authorization: 'Bearer ' + GATEWAY_TOKEN },
      });
      if (!resp.ok) return;
      var data = await resp.json();
      var items = Array.isArray(data.pending) ? data.pending : [];
      items.forEach(function (item) {
        upsertHitlPending({
          task_id: item.task_id,
          description: item.description,
          tool: item.tool,
          risk_level: item.risk_level,
          agent_id: item.agent_id,
          thread_id: item.thread_id,
          ts: Date.now(),
        });
      });
      restoreHitlDock();
    } catch (e) {}
  }

  function startHitlPolling() {
    if (hitlPollTimer) clearInterval(hitlPollTimer);
    hitlPollTimer = setInterval(function () {
      if (isOnline()) fetchHitlPendingFromGateway();
    }, 30000);
  }

  function stopHitlPolling() {
    if (hitlPollTimer) {
      clearInterval(hitlPollTimer);
      hitlPollTimer = null;
    }
  }

  function tryAutoApproveFromText(text) {
    var trimmed = (text || '').trim();
    if (!trimmed) return false;
    var list = loadHitlPendingList();
    if (!list.length) return false;
    if (!/^(批准|同意|approve|ok|好的|确认|yes)$/i.test(trimmed)) return false;
    var item = list[0];
    sendHitlDecision(item.task_id, 'approved', item.agent_id);
    UI().appendSystem('已根据「' + trimmed + '」自动提交批准（' + item.task_id + '）');
    return true;
  }

  function clearActivityStaleTimer() {
    if (activityStaleTimer) {
      clearTimeout(activityStaleTimer);
      activityStaleTimer = null;
    }
  }

  function scheduleActivityStaleTimer() {
    clearActivityStaleTimer();
    activityStaleTimer = setTimeout(function () {
      var box = el('agentActivity');
      if (box && box.classList.contains('visible')) {
        UI().setAgentActivity('thinking', '', true);
      }
    }, ACTIVITY_STALE_MS);
  }

  function applyAgentActivity(p) {
    if (!p || p.status !== 'activity') return;
    if (!isForThisDevice(p)) return;
    var phase = p.phase || 'idle';
    if (phase === 'idle') {
      clearActivityStaleTimer();
      UI().setAgentActivity(null);
      return;
    }
    UI().setAgentActivity(phase, p.detail || '', false);
    scheduleActivityStaleTimer();
  }

  function agentLabel(agentId) {
    var match = onlineAgents.find(function (a) { return a.device_id === agentId; });
    if (match && match.display_name) return match.display_name;
    return AGENT_LABELS[agentId] || agentId || 'Agent';
  }

  function sessionKey(s) {
    return (s.thread_id || '') + '|' + (s.agent_id || selectedAgentId);
  }

  function mergeInboxSessions(agentSessions, inboxThreads) {
    var map = {};
    (inboxThreads || []).forEach(function (t) {
      var s = {
        thread_id: t.thread_id,
        title: t.title || '新对话',
        agent_id: t.agent_id,
        updated_at: t.updated_at,
        active: false,
      };
      map[sessionKey(s)] = s;
    });
    (agentSessions || []).forEach(function (s) {
      var copy = Object.assign({}, s);
      if (!copy.agent_id) copy.agent_id = selectedAgentId;
      var key = sessionKey(copy);
      map[key] = Object.assign(map[key] || {}, copy);
    });
    return Object.keys(map).map(function (k) { return map[k]; }).sort(function (a, b) {
      return String(b.updated_at || '').localeCompare(String(a.updated_at || ''));
    });
  }

  async function fetchInboxThreads() {
    if (!GATEWAY_TOKEN) return [];
    var base = getApiBase();
    var url = base + '/v1/inbox/threads?user_id=' + encodeURIComponent(USER_ID)
      + '&token=' + encodeURIComponent(GATEWAY_TOKEN);
    try {
      var resp = await fetch(url, {
        headers: { Authorization: 'Bearer ' + GATEWAY_TOKEN },
      });
      if (!resp.ok) return [];
      var data = await resp.json();
      return Array.isArray(data.threads) ? data.threads : [];
    } catch (e) {
      return [];
    }
  }

  async function fetchInboxMessages(threadId, agentId) {
    if (!GATEWAY_TOKEN || !threadId || !agentId) return [];
    var base = getApiBase();
    var url = base + '/v1/inbox/messages?thread_id=' + encodeURIComponent(threadId)
      + '&agent_id=' + encodeURIComponent(agentId)
      + '&token=' + encodeURIComponent(GATEWAY_TOKEN);
    try {
      var resp = await fetch(url, {
        headers: { Authorization: 'Bearer ' + GATEWAY_TOKEN },
      });
      if (!resp.ok) return [];
      var data = await resp.json();
      var msgs = Array.isArray(data.messages) ? data.messages : [];
      return msgs.map(function (m) {
        return {
          role: m.role === 'user' ? 'user' : 'agent',
          text: m.text || '',
        };
      });
    } catch (e) {
      return [];
    }
  }

  function findSession(threadId) {
    return sessions.find(function (s) { return s.thread_id === threadId; }) || null;
  }

  function setSelectedAgentId(agentId) {
    selectedAgentId = agentId || DEFAULT_AGENT_ID;
    try { localStorage.setItem(CACHE_TARGET_AGENT, selectedAgentId); } catch (e) {}
    var sel = el('agentSelect');
    if (sel && sel.value !== selectedAgentId) sel.value = selectedAgentId;
  }

  function withUserId(payload) {
    var out = payload || {};
    if (!out.user_id) out.user_id = USER_ID;
    if (!out.source) out.source = 'web';
    return out;
  }

  function saveSessionsCache() {
    try {
      localStorage.setItem(CACHE_SESSIONS, JSON.stringify(sessions));
      saveActiveThreadForAgent(getSelectedAgentId(), activeThreadId);
    } catch (e) {}
  }

  function loadSessionsCache() {
    try {
      var raw = localStorage.getItem(CACHE_SESSIONS);
      if (!raw) return false;
      sessions = JSON.parse(raw);
      activeThreadId = loadActiveThreadForAgent(selectedAgentId);
      return sessions.length > 0;
    } catch (e) {
      return false;
    }
  }

  function saveHistoryCache(threadId, history, agentId) {
    if (!threadId || !Array.isArray(history)) return;
    try {
      localStorage.setItem(historyCacheKey(threadId, agentId), JSON.stringify(history));
    } catch (e) {}
  }

  function loadHistoryCache(threadId, agentId) {
    if (!threadId) return null;
    try {
      var raw = localStorage.getItem(historyCacheKey(threadId, agentId));
      if (raw) return JSON.parse(raw);
      var legacy = localStorage.getItem('lingji_history_v2_' + USER_ID + '_' + threadId);
      return legacy ? JSON.parse(legacy) : null;
    } catch (e) {
      return null;
    }
  }

  function restoreFromCache() {
    if (!loadSessionsCache()) return;
    renderSessionList(true);
    if (activeThreadId) {
      var history = loadHistoryCache(activeThreadId, selectedAgentId);
      if (history && history.length) {
        UI().renderHistory(history);
        UI().appendSystem('已加载本地缓存，连接后将与服务器同步');
      }
    }
  }

  function notifyClientIdMigrationOnce() {
    try {
      if (localStorage.getItem('lingji_client_migrated_v1')) return;
      if (localStorage.getItem(STORAGE_CLIENT_SOURCE) !== 'token') return;
      localStorage.setItem('lingji_client_migrated_v1', '1');
      UI().appendSystem(
        '已使用统一账号身份（' + USER_ID + '）；手机与电脑 Web 使用相同 token 时将共享会话。'
      );
    } catch (e) {}
  }

  function loadHitlResQueue() {
    try {
      var raw = localStorage.getItem(CACHE_HITL_QUEUE);
      return raw ? JSON.parse(raw) : [];
    } catch (e) {
      return [];
    }
  }

  function saveHitlResQueue(queue) {
    try {
      if (!queue.length) {
        localStorage.removeItem(CACHE_HITL_QUEUE);
      } else {
        localStorage.setItem(CACHE_HITL_QUEUE, JSON.stringify(queue));
      }
    } catch (e) {}
  }

  function enqueueHitlRes(taskId, decision, agentId) {
    var queue = loadHitlResQueue().filter(function (item) {
      return item.task_id !== taskId;
    });
    queue.push({
      task_id: taskId,
      decision: decision,
      target_agent_id: agentId || getSelectedAgentId(),
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
        device_id: CONNECTION_ID,
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

  function getSelectedAgentId() {
    return selectedAgentId || DEFAULT_AGENT_ID;
  }

  function saveSelectedAgentId(id) {
    setSelectedAgentId(id);
  }

  function withTargetAgent(payload) {
    return withUserId((function () {
      var out = payload || {};
      if (!out.target_agent_id) {
        out.target_agent_id = getSelectedAgentId();
      }
      out.command_agent_id = getSelectedAgentId();
      return out;
    })());
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
      var label = a.display_name || agentLabel(a.device_id);
      opt.textContent = label + ' · ' + a.device_id;
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
    var targetUser = payload.target_user_id;
    if (targetUser && targetUser === USER_ID) return true;
    var target = payload.target_device_id;
    if (!target) return true;
    return target === CONNECTION_ID;
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
      sessions = mergeInboxSessions(p.sessions, sessions);
      if (p.thread_id) activeThreadId = p.thread_id;
      else {
        var active = sessions.find(function (s) { return s.active; });
        if (active) activeThreadId = active.thread_id;
      }
      saveSessionsCache();
      renderSessionList();
    }
    if (p.pending_hitl) {
      var ph = hitlPayloadWithAgent(p.pending_hitl);
      upsertHitlPending(ph);
      showHitlRequest(ph, true);
    }
    if (Array.isArray(p.history) && activeThreadId) {
      var agentId = getSelectedAgentId();
      var localHist = loadHistoryCache(activeThreadId, agentId) || [];
      var merged = mergeHistoryPreferLonger(localHist, p.history);
      saveHistoryCache(activeThreadId, merged, agentId);
      UI().renderHistory(merged);
      enrichHistoryFromInbox(activeThreadId, agentId, merged);
    } else {
      restoreHitlDock();
    }
    if (p.status === 'session_switched' && p.text) {
      UI().appendSystem(p.text);
    }
    finishSessionSwitch();
    pendingSwitchThreadId = null;
  }

  function renderSessionList(force) {
    var sig = sessions.map(function (s) {
      return sessionKey(s) + ':' + (s.title || '') + ':' + (s.active ? '1' : '0');
    }).join('|');
    if (!force && sig === lastSessionListSig) {
      UI().updateSessionActiveClass(sessions, activeThreadId);
      return;
    }
    lastSessionListSig = sig;
    UI().renderSessionList(sessions, activeThreadId, switchSession, agentLabel);
  }

  function requestSessionList() {
    if (!isOnline()) return;
    ws.send(JSON.stringify({
      msg_id: 'list-' + (++msgId),
      msg_type: 'CMD_LIST_SESSIONS',
      device_id: CONNECTION_ID,
      timestamp: Date.now() / 1000,
      payload: withTargetAgent({}),
    }));
  }

  function sendSessionSwitch(threadId) {
    ws.send(JSON.stringify({
      msg_id: 'sw-' + (++msgId),
      msg_type: 'CMD_TEXT',
      device_id: CONNECTION_ID,
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
    var sess = findSession(threadId);
    var history = loadHistoryCache(threadId, (sess && sess.agent_id) || selectedAgentId);
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
    if (!threadId) {
      UI().closeSidebar();
      return;
    }
    var sess = findSession(threadId);
    if (sess && sess.agent_id) {
      setSelectedAgentId(sess.agent_id);
    }
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

    var agentId = (sess && sess.agent_id) || selectedAgentId;
    fetchInboxMessages(threadId, agentId).then(function (inboxHist) {
      var local = loadHistoryCache(threadId, agentId) || [];
      var merged = mergeHistoryPreferLonger(local, inboxHist);
      if (merged.length) {
        saveHistoryCache(threadId, merged, agentId);
        UI().renderHistory(merged);
      }
      sendSessionSwitch(threadId);
    });
    UI().closeSidebar();
  }

  function appendToHistoryCache(threadId, role, text, attachments, lingjiFiles) {
    if (!threadId) return;
    var agentId = getSelectedAgentId();
    var history = loadHistoryCache(threadId, agentId) || [];
    history.push({
      role: role,
      text: text || '',
      attachments: attachments || [],
      lingji_files: lingjiFiles || [],
    });
    saveHistoryCache(threadId, history, agentId);
  }

  function onConnected() {
    refreshOnlineAgents();
    restoreHitlDock();
    fetchHitlPendingFromGateway();
    startHitlPolling();
    flushHitlResQueue();
    notifyClientIdMigrationOnce();
    fetchInboxThreads().then(function (inboxThreads) {
      if (inboxThreads.length) {
        sessions = mergeInboxSessions(sessions, inboxThreads);
        saveSessionsCache();
        renderSessionList(true);
      }
    });
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
    if (activeThreadId) {
      var sess = findSession(activeThreadId);
      var agentId = (sess && sess.agent_id) || selectedAgentId;
      fetchInboxMessages(activeThreadId, agentId).then(function (inboxHist) {
        var local = loadHistoryCache(activeThreadId, agentId) || [];
        var merged = mergeHistoryPreferLonger(local, inboxHist);
        if (merged.length) {
          saveHistoryCache(activeThreadId, merged, agentId);
          UI().renderHistory(merged);
        }
      });
    }
    UI().appendSystem('正在同步会话列表…');
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
      saveActiveThreadForAgent(getSelectedAgentId(), null);
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

  function showHitlRequest(payload, skipPersist) {
    var enriched = hitlPayloadWithAgent(payload);
    if (!skipPersist) {
      enriched.ts = Date.now();
      upsertHitlPending(enriched);
    }
    UI().showHitlCard(enriched, function (taskId, decision) {
      if (!taskId) {
        UI().appendSystem('审批失败：缺少 task_id');
        return;
      }
      sendHitlDecision(taskId, decision, enriched.agent_id);
    });
  }

  function handleMessage(msg) {
    if (msg.msg_type === 'AGENT_RES') {
      var p = msg.payload || {};
      if (p.status === 'connected') {
        authenticated = true;
        UI().setConnectionStatus('已连接 (' + USER_ID + ')', true);
        UI().appendSystem('✅ 认证成功');
        onConnected();
        return;
      }
      if (p.status === 'rejected') {
        UI().appendSystem('❌ 认证失败');
        return;
      }
      if (!isForThisDevice(p)) return;
      if (p.status === 'activity') {
        applyAgentActivity(p);
        return;
      }
      if (p.status === 'sessions' || p.status === 'session_switched') {
        applySessionPayload(p);
        return;
      }
      if (switchingSession) finishSessionSwitch();
      if (p.thread_id) {
        activeThreadId = p.thread_id;
        saveSessionsCache();
      }
      if (p.status === 'queued') {
        UI().appendMessage('agent', '📦 ' + p.text);
        appendToHistoryCache(activeThreadId, 'agent', '📦 ' + p.text);
      } else if (p.text || (p.attachments && p.attachments.length) || (p.lingji_files && p.lingji_files.length)) {
        UI().appendMessage('agent', p.text || '', p.attachments, p.lingji_files);
        appendToHistoryCache(activeThreadId, 'agent', p.text || '', p.attachments, p.lingji_files);
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
        device_id: CONNECTION_ID,
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
        UI().setConnectionStatus('认证中... (' + USER_ID + ')', false);
        ws.send(JSON.stringify({
          msg_id: 'auth-' + (++msgId),
          msg_type: 'AUTH_REQ',
          device_id: CONNECTION_ID,
          timestamp: Date.now() / 1000,
          payload: { device_id: CONNECTION_ID, user_id: USER_ID, token: GATEWAY_TOKEN },
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
        stopHitlPolling();
        clearActivityStaleTimer();
        UI().setAgentActivity(null);
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
    if (text && tryAutoApproveFromText(text)) {
      UI().clearInput();
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
    UI().setAgentActivity('thinking');
    scheduleActivityStaleTimer();
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
    } else if (activeThreadId) {
      payload.thread_id = activeThreadId;
    }
    ws.send(JSON.stringify({
      msg_id: 'msg-' + (++msgId),
      msg_type: 'CMD_TEXT',
      device_id: CONNECTION_ID,
      timestamp: Date.now() / 1000,
      payload: withTargetAgent(payload),
    }));
    if (text) {
      UI().appendMessage('user', text);
      appendToHistoryCache(activeThreadId, 'user', text);
    }
    if (uploads && uploads.length) {
      UI().appendMessage('user', '', uploads);
      appendToHistoryCache(activeThreadId, 'user', '', uploads);
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
    restoreHitlDock();
    renderAgentSelect();

    var agentSelect = el('agentSelect');
    if (agentSelect) {
      agentSelect.addEventListener('change', function () {
        var prevAgent = getSelectedAgentId();
        saveActiveThreadForAgent(prevAgent, activeThreadId);
        setSelectedAgentId(agentSelect.value);
        activeThreadId = loadActiveThreadForAgent(getSelectedAgentId());
        UI().clearChat();
        if (activeThreadId) {
          var cached = loadHistoryCache(activeThreadId, getSelectedAgentId());
          if (cached && cached.length) {
            UI().renderHistory(cached);
          }
        }
        if (isOnline()) {
          restoreHitlDock();
          fetchHitlPendingFromGateway();
          requestSessionList();
        } else {
          UI().appendSystem('已切换到 ' + agentLabel(getSelectedAgentId()));
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


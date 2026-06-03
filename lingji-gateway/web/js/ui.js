/** 灵机 G6.4 — 纯 DOM 层（window.LingjiUI） */
(function () {
  'use strict';

  let userScrolledUp = false;

  function el(id) {
    return document.getElementById(id);
  }

  function isNearBottom(chat, threshold) {
    return chat.scrollHeight - chat.scrollTop - chat.clientHeight <= threshold;
  }

  function appendAttachments(parent, attachments) {
    if (!attachments || !attachments.length) return;
    const box = document.createElement('div');
    box.className = 'attachments';
    attachments.forEach(function (att) {
      const row = document.createElement('div');
      row.className = 'attachment';
      const link = document.createElement('a');
      link.href = att.download_path || '#';
      link.textContent = '⬇ ' + (att.name || 'download');
      link.setAttribute('download', att.name || 'download');
      const meta = document.createElement('span');
      meta.className = 'meta';
      meta.textContent = att.size_bytes ? Math.round(att.size_bytes / 1024) + ' KB' : '';
      row.appendChild(link);
      row.appendChild(meta);
      box.appendChild(row);
    });
    parent.appendChild(box);
  }

  window.LingjiUI = {
    clearChat: function () {
      const chat = el('chat');
      if (chat) chat.innerHTML = '';
    },

    renderHistory: function (history) {
      const chat = el('chat');
      if (!chat) return;
      const frag = document.createDocumentFragment();
      (history || []).forEach(function (item) {
        if (!item || !item.text) return;
        const m = document.createElement('div');
        m.className = 'msg ' + (item.role === 'user' ? 'user' : 'agent');
        const textNode = document.createElement('div');
        textNode.textContent = item.text;
        m.appendChild(textNode);
        frag.appendChild(m);
      });
      chat.innerHTML = '';
      chat.appendChild(frag);
      userScrolledUp = false;
      window.LingjiUI.scrollChatToBottom(true);
    },

    appendMessage: function (cls, text, attachments) {
      const chat = el('chat');
      if (!chat) return;
      const m = document.createElement('div');
      m.className = 'msg ' + cls;
      if (text) {
        const textNode = document.createElement('div');
        textNode.textContent = text;
        m.appendChild(textNode);
      }
      appendAttachments(m, attachments);
      chat.appendChild(m);
      window.LingjiUI.scrollChatToBottom(cls === 'user');
    },

    appendSystem: function (text) {
      window.LingjiUI.appendMessage('system', text);
    },

    showHitlCard: function (payload, onDecision) {
      const taskId = payload.task_id || '';
      if (taskId && document.querySelector('.msg.hitl[data-task-id="' + taskId + '"]')) {
        return;
      }
      const chat = el('chat');
      if (!chat) return;

      const m = document.createElement('div');
      m.className = 'msg hitl';
      m.dataset.taskId = taskId;

      const title = document.createElement('div');
      title.className = 'hitl-title';
      title.textContent = '⚠️ 危险操作需审批';
      m.appendChild(title);

      const desc = document.createElement('div');
      desc.className = 'hitl-desc';
      desc.textContent = payload.description || '请确认是否允许执行此操作';
      m.appendChild(desc);

      const metaParts = [];
      if (payload.tool) metaParts.push('工具: ' + payload.tool);
      if (payload.risk_level) metaParts.push('风险: ' + payload.risk_level);
      if (metaParts.length) {
        const meta = document.createElement('div');
        meta.className = 'hitl-meta';
        meta.textContent = metaParts.join(' · ');
        m.appendChild(meta);
      }

      const statusEl = document.createElement('div');
      statusEl.className = 'hitl-status';

      const actions = document.createElement('div');
      actions.className = 'hitl-actions';

      const btnApprove = document.createElement('button');
      btnApprove.type = 'button';
      btnApprove.className = 'hitl-btn approve';
      btnApprove.textContent = '批准';

      const btnReject = document.createElement('button');
      btnReject.type = 'button';
      btnReject.className = 'hitl-btn reject';
      btnReject.textContent = '拒绝';

      function decide(decision) {
        btnApprove.disabled = true;
        btnReject.disabled = true;
        statusEl.textContent = decision === 'approved' ? '已提交批准，等待 Agent 继续…' : '已提交拒绝';
        statusEl.style.color = decision === 'approved' ? '#4caf50' : '#ef5350';
        if (onDecision) onDecision(taskId, decision);
      }

      btnApprove.addEventListener('click', function () { decide('approved'); });
      btnReject.addEventListener('click', function () { decide('rejected'); });

      actions.appendChild(btnApprove);
      actions.appendChild(btnReject);
      m.appendChild(actions);
      m.appendChild(statusEl);
      chat.appendChild(m);
      window.LingjiUI.scrollChatToBottom(true);
    },

    renderSessionList: function (sessions, activeThreadId, onSelect) {
      const list = el('sessionList');
      if (!list) return;
      list.innerHTML = '';
      (sessions || []).forEach(function (s) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'session-item' + ((s.thread_id === activeThreadId || s.active) ? ' active' : '');
        btn.textContent = s.title || '新对话';
        btn.addEventListener('click', function () {
          if (onSelect) onSelect(s.thread_id);
        });
        list.appendChild(btn);
      });
    },

    updateSessionActiveClass: function (sessions, activeThreadId) {
      const list = el('sessionList');
      if (!list) return;
      const items = list.querySelectorAll('.session-item');
      items.forEach(function (btn, i) {
        const s = sessions[i];
        if (!s) return;
        btn.classList.toggle('active', s.thread_id === activeThreadId);
      });
    },

    renderPendingUploads: function (pendingUploads, onRemove) {
      const bar = el('pendingBar');
      if (!bar) return;
      bar.innerHTML = '';
      if (!pendingUploads.length) {
        bar.classList.remove('visible');
        return;
      }
      bar.classList.add('visible');
      pendingUploads.forEach(function (u, idx) {
        const chip = document.createElement('div');
        chip.className = 'pending-chip'
          + (u.status === 'uploading' ? ' uploading' : '')
          + (u.status === 'error' ? ' error' : '');
        const name = document.createElement('span');
        name.className = 'name';
        name.textContent = u.name || 'file';
        chip.appendChild(name);
        if (u.status === 'uploading') {
          const hint = document.createElement('span');
          hint.className = 'status-hint';
          hint.textContent = '上传中…';
          chip.appendChild(hint);
        } else if (u.status === 'error') {
          const hint = document.createElement('span');
          hint.className = 'status-hint';
          hint.textContent = '失败';
          chip.appendChild(hint);
        }
        if (u.status !== 'uploading') {
          const rm = document.createElement('button');
          rm.type = 'button';
          rm.setAttribute('aria-label', '移除');
          rm.textContent = '×';
          rm.addEventListener('click', function () {
            if (onRemove) onRemove(idx);
          });
          chip.appendChild(rm);
        }
        bar.appendChild(chip);
      });
    },

    setConnectionStatus: function (text, on) {
      const s = el('status');
      if (!s) return;
      s.textContent = text;
      s.className = on ? 'status' : 'status off';
    },

    setComposerDisabled: function (on) {
      const sendBtn = el('btnSend');
      const input = el('input');
      if (sendBtn) sendBtn.disabled = on;
      if (input) input.disabled = on;
    },

    getInputText: function () {
      const input = el('input');
      return input ? input.value.trim() : '';
    },

    clearInput: function () {
      const input = el('input');
      if (input) input.value = '';
    },

    focusInput: function () {
      const input = el('input');
      if (input) input.focus();
    },

    scrollChatToBottom: function (force) {
      const chat = el('chat');
      if (!chat) return;
      if (!force && userScrolledUp) return;
      chat.scrollTop = chat.scrollHeight;
      userScrolledUp = false;
    },

    setupChatScrollTracking: function () {
      const chat = el('chat');
      if (!chat) return;
      chat.addEventListener('scroll', function () {
        userScrolledUp = !isNearBottom(chat, 80);
      }, { passive: true });
    },

    setupKeyboardViewport: function () {
      const mainPanel = document.querySelector('.main-panel');
      const input = el('input');
      if (!window.visualViewport || !mainPanel) return;

      const update = function () {
        const vv = window.visualViewport;
        const gap = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
        mainPanel.style.paddingBottom = gap > 0 ? gap + 'px' : '';
      };

      visualViewport.addEventListener('resize', update);
      visualViewport.addEventListener('scroll', update);
      input.addEventListener('focus', function () {
        setTimeout(function () { window.LingjiUI.scrollChatToBottom(true); }, 300);
      });
    },

    toggleSidebar: function () {
      el('sidebar').classList.toggle('open');
      el('sidebarOverlay').classList.toggle('open');
    },

    closeSidebar: function () {
      el('sidebar').classList.remove('open');
      el('sidebarOverlay').classList.remove('open');
    },
  };
})();

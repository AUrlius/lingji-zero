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

  function appendLingjiFiles(parent, lingjiFiles) {
    if (!lingjiFiles || !lingjiFiles.length) return;
    var box = document.createElement('div');
    box.className = 'lingji-files';
    lingjiFiles.forEach(function (item) {
      var chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'lf-id-chip';
      var lfId = item.lingji_file_id || '';
      chip.textContent = lfId + (item.name ? ' · ' + item.name : '');
      chip.title = '点击复制灵机文件 ID';
      chip.addEventListener('click', function () {
        if (navigator.clipboard && lfId) {
          navigator.clipboard.writeText(lfId).catch(function () {});
        }
      });
      box.appendChild(chip);
    });
    parent.appendChild(box);
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
        if (!item) return;
        if (!item.text && !(item.attachments && item.attachments.length)
            && !(item.lingji_files && item.lingji_files.length)) return;
        const m = document.createElement('div');
        m.className = 'msg ' + (item.role === 'user' ? 'user' : 'agent');
        if (item.text) {
          const textNode = document.createElement('div');
          textNode.textContent = item.text;
          m.appendChild(textNode);
        }
        appendAttachments(m, item.attachments);
        appendLingjiFiles(m, item.lingji_files);
        frag.appendChild(m);
      });
      chat.innerHTML = '';
      chat.appendChild(frag);
      userScrolledUp = false;
      window.LingjiUI.scrollChatToBottom(true);
    },

    appendMessage: function (cls, text, attachments, lingjiFiles) {
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
      appendLingjiFiles(m, lingjiFiles);
      chat.appendChild(m);
      window.LingjiUI.scrollChatToBottom(cls === 'user');
    },

    appendSystem: function (text) {
      window.LingjiUI.appendMessage('system', text);
    },

    showHitlCard: function (payload, onDecision, onDismiss) {
      const taskId = payload.task_id || '';
      const dock = el('hitlDock');
      if (!dock) return;
      if (taskId && dock.querySelector('.msg.hitl[data-task-id="' + taskId + '"]')) {
        return;
      }

      const m = document.createElement('div');
      m.className = 'msg hitl';
      m.dataset.taskId = taskId;

      const title = document.createElement('div');
      title.className = 'hitl-title';
      title.textContent = '需您授权';
      m.appendChild(title);

      if (payload.agent_id || payload.agent_label) {
        const src = document.createElement('div');
        src.className = 'hitl-source';
        src.textContent = '来源：' + (payload.agent_label || payload.agent_id || 'Agent');
        m.appendChild(src);
      }

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

      const btnDismiss = document.createElement('button');
      btnDismiss.type = 'button';
      btnDismiss.className = 'hitl-btn dismiss';
      btnDismiss.textContent = '放弃此审批';

      function decide(decision) {
        btnApprove.disabled = true;
        btnReject.disabled = true;
        btnDismiss.disabled = true;
        statusEl.textContent = decision === 'approved' ? '已提交批准，等待 Agent 继续…' : '已提交拒绝';
        statusEl.style.color = decision === 'approved' ? '#4caf50' : '#ef5350';
        if (onDecision) onDecision(taskId, decision);
      }

      btnApprove.addEventListener('click', function () { decide('approved'); });
      btnReject.addEventListener('click', function () { decide('rejected'); });
      btnDismiss.addEventListener('click', function () {
        btnApprove.disabled = true;
        btnReject.disabled = true;
        btnDismiss.disabled = true;
        statusEl.textContent = '已放弃此审批';
        statusEl.style.color = '#ffb74d';
        if (onDismiss) onDismiss(taskId);
      });

      actions.appendChild(btnApprove);
      actions.appendChild(btnReject);
      actions.appendChild(btnDismiss);
      m.appendChild(actions);
      m.appendChild(statusEl);
      dock.appendChild(m);
      dock.classList.add('visible');
    },

    clearHitlDock: function () {
      const dock = el('hitlDock');
      if (!dock) return;
      dock.innerHTML = '';
      dock.classList.remove('visible');
    },

    renderJobList: function (jobs, onSelect) {
      const list = el('jobList');
      if (!list) return;
      list.innerHTML = '';
      (jobs || []).forEach(function (j) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'job-item job-' + (j.status || 'planned');
        const id = document.createElement('span');
        id.className = 'job-id';
        id.textContent = j.job_id || '';
        const st = document.createElement('span');
        st.className = 'job-status';
        st.textContent = j.status || '';
        const intent = document.createElement('span');
        intent.className = 'job-intent';
        intent.textContent = j.intent || j.playbook || '';
        btn.appendChild(id);
        btn.appendChild(st);
        btn.appendChild(intent);
        if (typeof onSelect === 'function') {
          btn.addEventListener('click', function () { onSelect(j); });
        }
        list.appendChild(btn);
      });
      if (!(jobs || []).length) {
        const empty = document.createElement('div');
        empty.className = 'job-empty';
        empty.textContent = '暂无工单';
        list.appendChild(empty);
      }
    },

    upsertJobCard: function (job) {
      const chat = el('chat');
      if (!chat || !job || !job.job_id) return;
      var existing = chat.querySelector('.msg.job-card[data-job-id="' + job.job_id + '"]');
      const m = existing || document.createElement('div');
      m.className = 'msg job-card';
      m.dataset.jobId = job.job_id;
      m.innerHTML = '';
      const head = document.createElement('div');
      head.className = 'job-card-head';
      head.textContent = (job.job_id || '') + ' · ' + (job.status || '');
      m.appendChild(head);
      if (job.intent) {
        const intent = document.createElement('div');
        intent.className = 'job-card-intent';
        intent.textContent = job.intent;
        m.appendChild(intent);
      }
      const ul = document.createElement('ul');
      ul.className = 'job-steps';
      (job.steps || []).forEach(function (st) {
        const li = document.createElement('li');
        li.className = 'job-step job-step-' + (st.status || 'pending');
        var mark = '○';
        if (st.status === 'completed') mark = '✓';
        else if (st.status === 'failed') mark = '✕';
        else if (st.status === 'running' || st.status === 'dispatched') mark = '…';
        li.textContent = mark + ' ' + (st.name || st.step_id) + ' · ' + (st.status || '');
        ul.appendChild(li);
      });
      m.appendChild(ul);
      if (!existing) chat.appendChild(m);
      window.LingjiUI.scrollChatToBottom(false);
    },

    setStaffPresence: function (text) {
      const n = el('staffPresence');
      if (n) n.textContent = text || '';
    },

    renderSessionList: function (sessions, activeThreadId, onSelect, agentLabelFn, formatTimeFn) {
      const list = el('sessionList');
      if (!list) return;
      list.innerHTML = '';
      (sessions || []).forEach(function (s) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'session-item' + ((s.thread_id === activeThreadId || s.active) ? ' active' : '');
        const main = document.createElement('div');
        main.className = 'session-main';
        const title = document.createElement('span');
        title.className = 'session-title';
        title.textContent = s.title || '新交办';
        main.appendChild(title);
        if (formatTimeFn && s.updated_at) {
          const time = document.createElement('span');
          time.className = 'session-time';
          time.textContent = formatTimeFn(s.updated_at);
          main.appendChild(time);
        }
        btn.appendChild(main);
        if (s.agent_id && agentLabelFn) {
          const badge = document.createElement('span');
          badge.className = 'session-agent';
          badge.textContent = agentLabelFn(s.agent_id);
          btn.appendChild(badge);
        }
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
      if (!on) {
        window.LingjiUI.setAgentActivity(null);
      }
    },

    setAgentActivity: function (phase, detail, stale) {
      const box = el('agentActivity');
      const label = el('agentActivityLabel');
      if (!box || !label) return;
      if (!phase || phase === 'idle') {
        box.hidden = true;
        box.classList.remove('visible', 'stale');
        label.textContent = '';
        return;
      }
      var textMap = {
        received: '已收到，正在处理…',
        thinking: '处理中…',
        tool: '执行工具' + (detail ? '：' + detail : '…'),
        waiting_hitl: '等待审批（见顶部批准条）',
      };
      label.textContent = textMap[phase] || phase;
      if (stale) {
        label.textContent = '仍在运行，若久无响应请查看 HITL 或刷新';
        box.classList.add('stale');
      } else {
        box.classList.remove('stale');
      }
      box.hidden = false;
      box.classList.add('visible');
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

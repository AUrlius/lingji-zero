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

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function applyInlineMd(s) {
    return s
      .replace(/`([^`]+)`/g, '<code class="md-code">$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  }

  function isMdTableSep(line) {
    return /^\|?[\s:\-|]+\|?$/.test(line) && line.indexOf('-') !== -1;
  }

  function renderMdTable(lines) {
    var rows = [];
    lines.forEach(function (line) {
      if (isMdTableSep(line)) return;
      rows.push(line.replace(/^\|/, '').replace(/\|$/, '').split('|').map(function (c) {
        return applyInlineMd(c.trim());
      }));
    });
    if (!rows.length) return '';
    var head = rows[0];
    var body = rows.slice(1);
    var html = '<div class="md-table-wrap"><table class="md-table"><thead><tr>';
    html += head.map(function (c) { return '<th>' + c + '</th>'; }).join('');
    html += '</tr></thead><tbody>';
    html += body.map(function (r) {
      return '<tr>' + r.map(function (c) { return '<td>' + c + '</td>'; }).join('') + '</tr>';
    }).join('');
    html += '</tbody></table></div>';
    return html;
  }

  function renderSafeMarkdown(raw) {
    if (!raw) return '';
    var text = escapeHtml(raw).replace(/\r\n/g, '\n');
    var fences = [];
    text = text.replace(/```[\w-]*\n?([\s\S]*?)```/g, function (_, code) {
      var i = fences.length;
      fences.push('<pre class="md-pre"><code>' + code.replace(/\n$/, '') + '</code></pre>');
      return '\n\n%%FENCE' + i + '%%\n\n';
    });
    return text.split(/\n{2,}/).map(function (block) {
      var trimmed = block.trim();
      if (!trimmed) return '';
      var fence = /^%%FENCE(\d+)%%$/.exec(trimmed);
      if (fence) return fences[Number(fence[1])] || '';
      var lines = block.split('\n');
      var nonempty = lines.filter(function (l) { return l.trim(); });
      var tableLines = nonempty.filter(function (l) { return l.indexOf('|') !== -1; });
      if (tableLines.length >= 2 && tableLines.length === nonempty.length) {
        return renderMdTable(tableLines);
      }
      if (nonempty.length && nonempty.every(function (l) { return /^[-*]\s/.test(l.trim()); })) {
        return '<ul class="md-list">' + nonempty.map(function (l) {
          return '<li>' + applyInlineMd(l.trim().replace(/^[-*]\s/, '')) + '</li>';
        }).join('') + '</ul>';
      }
      return '<p class="md-p">' + applyInlineMd(trimmed.replace(/\n/g, '<br>')) + '</p>';
    }).join('');
  }

  function fillMessage(m, cls, text, attachments, lingjiFiles) {
    if (cls === 'user' || cls === 'agent') {
      var who = document.createElement('div');
      who.className = 'msg-role';
      who.textContent = cls === 'user' ? '你' : '空城记';
      m.appendChild(who);
    }
    if (text) {
      var body = document.createElement('div');
      body.className = 'msg-body';
      if (cls === 'agent') body.innerHTML = renderSafeMarkdown(text);
      else body.textContent = text;
      m.appendChild(body);
    }
    appendAttachments(m, attachments);
    appendLingjiFiles(m, lingjiFiles);
  }

  function removeTyping() {
    var chat = el('chat');
    if (!chat) return;
    var n = chat.querySelector('.msg.typing');
    if (n) n.remove();
  }

  function upsertTyping(label) {
    var chat = el('chat');
    if (!chat) return;
    var n = chat.querySelector('.msg.typing');
    if (!n) {
      n = document.createElement('div');
      n.className = 'msg agent typing';
      n.setAttribute('aria-live', 'polite');
      var who = document.createElement('div');
      who.className = 'msg-role';
      who.textContent = '空城记';
      n.appendChild(who);
      var row = document.createElement('div');
      row.className = 'typing-row';
      var dots = document.createElement('span');
      dots.className = 'typing-dots';
      dots.setAttribute('aria-hidden', 'true');
      dots.innerHTML = '<i></i><i></i><i></i>';
      var lab = document.createElement('span');
      lab.className = 'typing-label';
      row.appendChild(dots);
      row.appendChild(lab);
      n.appendChild(row);
      chat.appendChild(n);
    }
    var labEl = n.querySelector('.typing-label');
    if (labEl) labEl.textContent = label || '处理中';
    window.LingjiUI.scrollChatToBottom(false);
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
        var role = item.role === 'user' ? 'user' : 'agent';
        const m = document.createElement('div');
        m.className = 'msg ' + role;
        fillMessage(m, role, item.text, item.attachments, item.lingji_files);
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
      if (cls === 'user' || cls === 'agent') removeTyping();
      const m = document.createElement('div');
      m.className = 'msg ' + cls;
      fillMessage(m, cls, text, attachments, lingjiFiles);
      chat.appendChild(m);
      window.LingjiUI.scrollChatToBottom(cls === 'user');
    },

    appendSystem: function (text) {
      window.LingjiUI.appendMessage('system', text);
    },

    showHitlCard: function (payload, onDecision, onDismiss) {
      if (payload && payload.escalation === 'scheduler') return;
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

    renderJobList: function (jobs, onSelect, fmt) {
      const list = el('jobList');
      if (!list) return;
      fmt = fmt || {};
      list.innerHTML = '';
      (jobs || []).forEach(function (j) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'job-item job-' + (j.status || 'planned');
        const id = document.createElement('span');
        id.className = 'job-id';
        id.textContent = j.job_id || '';
        const pill = document.createElement('span');
        var label = fmt.statusLabel ? fmt.statusLabel(j.status) : (j.status || '');
        pill.className = 'job-pill job-pill-' + (j.status || 'planned');
        pill.textContent = label;
        const time = document.createElement('span');
        time.className = 'job-time';
        var rel = (fmt.formatRelative && j.updated_at) ? fmt.formatRelative(j.updated_at) : '';
        var clock = (fmt.formatClock && j.updated_at) ? fmt.formatClock(j.updated_at) : '';
        var bits = [];
        if (rel) bits.push(rel);
        if (clock) bits.push(clock);
        time.textContent = bits.join(' · ');
        const intent = document.createElement('span');
        intent.className = 'job-intent';
        intent.textContent = j.intent || j.playbook || '';
        btn.appendChild(id);
        btn.appendChild(pill);
        btn.appendChild(intent);
        btn.appendChild(time);
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

    upsertJobCard: function (job, fmt) {
      const chat = el('chat');
      if (!chat || !job || !job.job_id) return;
      fmt = fmt || {};
      var existing = chat.querySelector('.msg.job-card[data-job-id="' + job.job_id + '"]');
      const m = existing || document.createElement('div');
      m.className = 'msg job-card artifact';
      m.dataset.jobId = job.job_id;
      m.innerHTML = '';
      const head = document.createElement('div');
      head.className = 'job-card-head';
      head.textContent = job.job_id || '';
      m.appendChild(head);

      var closed = job.status === 'completed' || job.status === 'failed';
      var durationEnd = closed ? (job.closed_at || job.updated_at) : '';
      var durationText = (closed && fmt.formatDuration)
        ? fmt.formatDuration(job.created_at, durationEnd)
        : '';
      const progress = document.createElement('div');
      progress.className = 'job-card-progress';
      if (job.status === 'completed') {
        progress.classList.add('is-done');
        progress.textContent = durationText ? ('已完成，耗时 ' + durationText) : '已完成';
      } else if (job.status === 'failed') {
        progress.classList.add('is-failed');
        progress.textContent = durationText ? ('失败，耗时 ' + durationText) : '失败';
      } else {
        progress.classList.add('is-busy');
        progress.textContent = '处理中';
      }
      m.appendChild(progress);

      function addMeta(label, value) {
        if (!value) return;
        const row = document.createElement('div');
        row.className = 'job-card-meta';
        row.textContent = label + '：' + value;
        m.appendChild(row);
      }

      var executorId = '';
      if (job.plan && job.plan.executor_id) executorId = job.plan.executor_id;
      if (!executorId && job.steps) {
        for (var i = 0; i < job.steps.length; i++) {
          if (job.steps[i].executor_id) {
            executorId = job.steps[i].executor_id;
            break;
          }
        }
      }

      addMeta('意图', job.intent);
      addMeta('剧本', job.playbook);
      addMeta('执行机', executorId ? (fmt.executorLabel ? fmt.executorLabel(executorId) : executorId) : '');
      addMeta('交办', fmt.formatClock ? fmt.formatClock(job.created_at) : job.created_at);
      addMeta('更新', fmt.formatClock ? fmt.formatClock(job.updated_at) : job.updated_at);
      if (job.closed_at && closed) {
        addMeta('结案', fmt.formatClock ? fmt.formatClock(job.closed_at) : job.closed_at);
      }
      addMeta('摘要', job.summary || job.error);

      const ul = document.createElement('ul');
      ul.className = 'job-steps';
      (job.steps || []).forEach(function (st) {
        const li = document.createElement('li');
        li.className = 'job-step job-step-' + (st.status || 'pending');
        var mark = '○';
        if (st.status === 'completed') mark = '✓';
        else if (st.status === 'failed') mark = '✕';
        else if (st.status === 'running' || st.status === 'dispatched') mark = '…';
        var stepBits = [mark + ' ' + (st.name || st.step_id)];
        var stepStatus = fmt.statusLabel ? fmt.statusLabel(st.status) : (st.status || '');
        if (stepStatus) stepBits.push(stepStatus);
        var stepTimes = [];
        if (st.started_at && fmt.formatClock) stepTimes.push(fmt.formatClock(st.started_at));
        if (st.completed_at && fmt.formatClock) stepTimes.push(fmt.formatClock(st.completed_at));
        if (stepTimes.length) stepBits.push(stepTimes.join('–'));
        if (st.error) stepBits.push(st.error);
        li.textContent = stepBits.join(' · ');
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

    setConnectionStatus: function (text, on, hint) {
      const s = el('status');
      if (!s) return;
      s.textContent = text;
      s.className = on ? 'status' : 'status off';
      if (hint) s.title = hint;
      else s.removeAttribute('title');
      if (!on) {
        window.LingjiUI.setAgentActivity(null);
      }
    },

    setHeaderTitle: function (title) {
      var h = document.querySelector('.header h1');
      if (h) h.textContent = title || '灵机';
    },

    setAgentActivity: function (phase, detail, stale) {
      const box = el('agentActivity');
      const label = el('agentActivityLabel');
      if (!box || !label) return;
      if (!phase || phase === 'idle') {
        box.hidden = true;
        box.classList.remove('visible', 'stale');
        label.textContent = '';
        removeTyping();
        return;
      }
      var textMap = {
        received: '已收到，正在处理…',
        thinking: '处理中…',
        tool: '执行工具' + (detail ? '：' + detail : '…'),
        waiting_hitl: '等待审批（见顶部批准条）',
      };
      var shown = textMap[phase] || phase;
      label.textContent = shown;
      if (stale) {
        shown = '仍在运行，若久无响应请查看 HITL 或刷新';
        label.textContent = shown;
        box.classList.add('stale');
      } else {
        box.classList.remove('stale');
      }
      box.hidden = false;
      box.classList.add('visible');
      if (phase === 'waiting_hitl') removeTyping();
      else upsertTyping(stale ? shown : (phase === 'thinking' || phase === 'received' ? '处理中' : shown));
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

// MODULE: tasks — 全局浮动任务面板
// ══════════════════════════════════════════════════════════
// 跨页面持久显示运行中的任务进度，不随路由切换丢失。
// 任何模块提交任务后调用 trackTask(taskId, label) 即可。
//
// 设计原则：
// - 当前页面的 pollTask 负责轮询 + 调用 updateTask 同步状态
// - TaskPanel 自身仅在页面切换后（pollTask 丢失）接管轮询
// - 不创建未使用的 Promise，避免内存泄漏

const TaskPanel = (() => {
  // ── 状态 ──
  const _tasks = new Map();  // taskId → { label, status, progress, message, startTime, endTime }
  let _panel = null;
  let _body = null;
  let _badge = null;
  let _collapsed = false;
  let _pollTimer = null;
  let _pollRunning = false;  // 防止并发轮询
  let _dragState = null;
  let _userCollapsed = false;  // 用户主动折叠过，阻止自动展开

  const MAX_HISTORY = 20;     // 最多保留已完成任务数
  const POLL_BASE = 1200;     // 轮询基础间隔 ms（比 pollTask 慢，避免重复请求）
  const POLL_MAX = 5000;      // 轮询最大间隔 ms
  const GC_DELAY = 30000;     // 已完成后多久移除（30s）

  // ── 初始化 ──

  function _init() {
    if (_panel) return;

    _panel = document.createElement('div');
    _panel.id = 'task-panel';
    _panel.className = 'task-panel';
    _panel.innerHTML = `
      <div class="task-panel-header" id="task-panel-header">
        <span class="task-panel-title">⏳ 任务</span>
        <span class="task-panel-badge" id="task-panel-badge">0</span>
        <button class="task-panel-toggle" id="task-panel-toggle" title="展开/收起">▲</button>
      </div>
      <div class="task-panel-body" id="task-panel-body"></div>
    `;
    document.body.appendChild(_panel);

    _body = document.getElementById('task-panel-body');
    _badge = document.getElementById('task-panel-badge');

    // 折叠/展开
    document.getElementById('task-panel-toggle').addEventListener('click', (e) => {
      e.stopPropagation();
      _toggleCollapse(true);
    });

    // 点击 header 也能折叠/展开
    document.getElementById('task-panel-header').addEventListener('click', (e) => {
      if (e.target.tagName === 'BUTTON') return;
      _toggleCollapse(true);
    });

    // 拖拽移动
    _initDrag();

    // 恢复折叠状态
    const savedCollapsed = localStorage.getItem('task_panel_collapsed');
    if (savedCollapsed === 'true') {
      _collapsed = true;
      _userCollapsed = true;
      _panel.classList.add('collapsed');
      document.getElementById('task-panel-toggle').textContent = '▼';
    }

    // 恢复位置
    const savedPos = localStorage.getItem('task_panel_pos');
    if (savedPos) {
      try {
        const { right, bottom } = JSON.parse(savedPos);
        _panel.style.right = right + 'px';
        _panel.style.bottom = bottom + 'px';
        _panel.style.left = 'auto';
        _panel.style.top = 'auto';
      } catch {}
    }

    // 页面重新可见时，检查是否有需要接管轮询的任务
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) _ensurePolling();
    });
  }

  function _toggleCollapse(userInitiated) {
    _collapsed = !_collapsed;
    _panel.classList.toggle('collapsed', _collapsed);
    document.getElementById('task-panel-toggle').textContent = _collapsed ? '▼' : '▲';
    if (userInitiated) {
      _userCollapsed = _collapsed;
      localStorage.setItem('task_panel_collapsed', _collapsed);
    }
  }

  function _initDrag() {
    const header = document.getElementById('task-panel-header');
    header.style.cursor = 'move';

    header.addEventListener('mousedown', (e) => {
      if (e.target.tagName === 'BUTTON') return;
      e.preventDefault();
      const rect = _panel.getBoundingClientRect();
      _dragState = {
        offsetX: e.clientX - rect.left,
        offsetY: e.clientY - rect.top,
      };
      _panel.classList.add('dragging');
    });

    document.addEventListener('mousemove', (e) => {
      if (!_dragState) return;
      const x = e.clientX - _dragState.offsetX;
      const y = e.clientY - _dragState.offsetY;
      _panel.style.left = Math.max(0, Math.min(x, window.innerWidth - 100)) + 'px';
      _panel.style.top = Math.max(0, Math.min(y, window.innerHeight - 50)) + 'px';
      _panel.style.right = 'auto';
      _panel.style.bottom = 'auto';
    });

    document.addEventListener('mouseup', () => {
      if (!_dragState) return;
      _panel.classList.remove('dragging');
      // 保存位置
      const rect = _panel.getBoundingClientRect();
      const right = window.innerWidth - rect.right;
      const bottom = window.innerHeight - rect.bottom;
      localStorage.setItem('task_panel_pos', JSON.stringify({
        right: Math.max(0, Math.round(right)),
        bottom: Math.max(0, Math.round(bottom)),
      }));
      _dragState = null;
    });
  }

  // ── 任务追踪 ──

  /**
   * 注册一个任务到面板（不创建 Promise，纯追踪）。
   * @param {string} taskId - Celery task ID
   * @param {string} label - 显示名称
   */
  function trackTask(taskId, label) {
    if (!taskId) return;
    _init();

    if (!_tasks.has(taskId)) {
      _tasks.set(taskId, {
        id: taskId,
        label: label || taskId,
        status: 'pending',
        progress: 0,
        message: '等待中...',
        startTime: Date.now(),
        endTime: null,
        _lastUpdateTime: Date.now(),
      });
      _render();

      // 有新任务时自动展开（仅用户未手动折叠时）
      if (_collapsed && !_userCollapsed) {
        _toggleCollapse(false);
      }
    }

    // 启动兜底轮询（当 pollTask 不活跃时接管）
    _ensurePolling();
  }

  /** 更新任务状态（由 pollTask 调用） */
  function updateTask(taskId, info) {
    const task = _tasks.get(taskId);
    if (!task) return;

    task.progress = info.progress ?? task.progress;
    // 只有 API 返回了有效消息才覆盖（避免丢失实际进度消息）
    if (info.message && info.message.trim()) {
      task.message = info.message;
    }
    task._lastUpdateTime = Date.now();

    if (info.status && info.status !== task.status) {
      task.status = info.status;
      // 首次从 pending 变为 running 时，确保消息不再是初始占位符
      if (info.status === 'running' && task.message === '等待中...') {
        task.message = info.message || '任务执行中...';
      }
      if (['success', 'failed', 'cancelled', 'timeout'].includes(info.status)) {
        task.endTime = Date.now();
      }
    }

    _render();
  }

  /** 取消任务 */
  async function cancelTask(taskId) {
    try {
      await api(`/tasks/${taskId}/cancel`, { method: 'POST' });
      updateTask(taskId, { status: 'cancelled' });
      toast('任务已取消');
    } catch (e) {
      toast('取消失败: ' + e.message, 'error');
    }
  }

  // ── 兜底轮询 ──
  // 仅在页面切换后（pollTask 停止）对长时间未更新的任务进行轮询

  function _hasStaleTasks() {
    const now = Date.now();
    for (const task of _tasks.values()) {
      if (['success', 'failed', 'cancelled', 'timeout'].includes(task.status)) continue;
      // 超过 5 秒未被 pollTask 更新，认为需要兜底轮询
      if (now - task._lastUpdateTime > 5000) return true;
    }
    return false;
  }

  function _ensurePolling() {
    if (_pollTimer || _pollRunning) return;
    if (!_hasStaleTasks()) return;
    _pollLoop();
  }

  async function _pollLoop() {
    if (_pollRunning) return;
    _pollRunning = true;

    try {
      const now = Date.now();
      const activeIds = [];
      for (const [id, task] of _tasks) {
        if (['success', 'failed', 'cancelled', 'timeout'].includes(task.status)) continue;
        // 只轮询超过 5 秒未被 pollTask 更新的任务
        if (now - task._lastUpdateTime > 5000) {
          activeIds.push(id);
        }
      }

      if (activeIds.length === 0) {
        _pollTimer = null;
        return;
      }

      // 并发轮询
      await Promise.allSettled(activeIds.map(async (id) => {
        try {
          const info = await api(`/tasks/${id}`);
          updateTask(id, info);
        } catch {}
      }));
    } finally {
      _pollRunning = false;
    }

    // 清理过期已完成任务
    _gcCompleted();

    // 继续轮询
    const delay = _hasStaleTasks() ? POLL_BASE : POLL_MAX;
    _pollTimer = setTimeout(() => {
      _pollTimer = null;
      _pollLoop();
    }, delay);
  }

  function _gcCompleted() {
    const now = Date.now();
    for (const [id, task] of _tasks) {
      if (['success', 'failed', 'cancelled', 'timeout'].includes(task.status)) {
        if (task.endTime && now - task.endTime > GC_DELAY) {
          _tasks.delete(id);
        }
      }
    }
  }

  // ── 渲染 ──

  function _statusBadge(status) {
    const map = {
      pending: { text: '排队中', cls: 'st-pending' },
      running: { text: '执行中', cls: 'st-running' },
      success: { text: '完成', cls: 'st-success' },
      failed:  { text: '失败', cls: 'st-failed' },
      cancelled: { text: '已取消', cls: 'st-cancelled' },
      timeout: { text: '超时', cls: 'st-failed' },
    };
    const s = map[status] || map.pending;
    return `<span class="task-status-badge ${s.cls}">${s.text}</span>`;
  }

  function _render() {
    if (!_body) return;

    const entries = [..._tasks.values()];
    const active = entries.filter(t => !['success', 'failed', 'cancelled', 'timeout'].includes(t.status));
    const done = entries.filter(t => ['success', 'failed', 'cancelled', 'timeout'].includes(t.status))
      .sort((a, b) => (b.endTime || 0) - (a.endTime || 0));

    // 徽章 + 标题
    _badge.textContent = active.length;
    _badge.style.display = active.length > 0 ? 'inline-flex' : 'none';
    _panel.classList.toggle('has-active', active.length > 0);

    // 标题显示当前状态概要
    const titleEl = _panel.querySelector('.task-panel-title');
    if (titleEl) {
      if (active.length === 0) {
        titleEl.textContent = '⏳ 任务';
      } else if (active.length === 1) {
        const t = active[0];
        const st = t.status === 'running' ? '执行中' : t.status === 'pending' ? '排队中' : '处理中';
        titleEl.textContent = `⏳ ${_esc(t.label)} · ${st}`;
      } else {
        titleEl.textContent = `⏳ ${active.length} 个任务运行中`;
      }
    }

    let html = '';

    // 活跃任务
    for (const t of active) {
      const elapsed = _fmtElapsed(Date.now() - t.startTime);
      const pct = t.progress || 0;
      // 根据状态决定显示什么消息
      let msg = t.message;
      if (t.status === 'pending' && t.message === '等待中...') {
        msg = '已提交，等待 Worker 处理...';
      }
      html += `<div class="task-item task-active">
        <div class="task-item-head">
          <span class="task-item-label">${_esc(t.label)}</span>
          ${_statusBadge(t.status)}
          <span class="task-item-elapsed">${elapsed}</span>
        </div>
        <div class="task-item-bar"><div class="task-item-fill" style="width:${pct}%"></div></div>
        <div class="task-item-msg">${_esc(msg)} · ${pct}%</div>
        <button class="task-item-cancel" onclick="TaskPanel.cancelTask('${t.id}')" title="取消">⏹</button>
      </div>`;
    }

    // 最近完成的任务（最多 5 条）
    const recentDone = done.slice(0, 5);
    if (recentDone.length > 0) {
      if (active.length > 0) html += '<div class="task-divider">最近完成</div>';
      for (const t of recentDone) {
        const icon = t.status === 'success' ? '✅' : t.status === 'cancelled' ? '⏹' : '❌';
        const elapsed = t.endTime ? _fmtElapsed(t.endTime - t.startTime) : '';
        html += `<div class="task-item task-done task-${t.status}">
          <div class="task-item-head">
            <span class="task-item-label">${icon} ${_esc(t.label)}</span>
            <span class="task-item-elapsed">${elapsed}</span>
          </div>
        </div>`;
      }
    }

    if (!html) {
      html = '<div class="task-empty">暂无任务</div>';
    }

    _body.innerHTML = html;
  }

  function _fmtElapsed(ms) {
    if (ms < 1000) return '';
    const s = Math.floor(ms / 1000);
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    return `${m}m${s % 60}s`;
  }

  function _esc(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // 定时刷新活跃任务的耗时显示
  setInterval(() => {
    for (const task of _tasks.values()) {
      if (!['success', 'failed', 'cancelled', 'timeout'].includes(task.status)) {
        _render();
        break;
      }
    }
  }, 3000);

  // ── 公开 API ──

  return {
    trackTask,
    updateTask,
    cancelTask,
    /** 获取当前活跃任务数 */
    get activeCount() {
      let n = 0;
      for (const t of _tasks.values()) {
        if (!['success', 'failed', 'cancelled', 'timeout'].includes(t.status)) n++;
      }
      return n;
    },
    /** 获取所有任务（调试用） */
    get tasks() { return _tasks; },
  };
})();

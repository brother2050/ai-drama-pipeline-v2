// MODULE: tasks — 全局浮动任务面板
// ══════════════════════════════════════════════════════════
// 跨页面持久显示运行中的任务进度，不随路由切换丢失。
// 任何模块提交任务后调用 trackTask(taskId, label) 即可。

const TaskPanel = (() => {
  // ── 状态 ──
  const _tasks = new Map();  // taskId → { label, status, progress, message, startTime, endTime }
  let _panel = null;
  let _body = null;
  let _badge = null;
  let _collapsed = false;
  let _pollTimer = null;
  let _dragState = null;

  const MAX_HISTORY = 20;     // 最多保留已完成任务数
  const POLL_BASE = 800;      // 轮询基础间隔 ms
  const POLL_MAX = 5000;      // 轮询最大间隔 ms

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
      _toggleCollapse();
    });

    // 点击 header 也能折叠/展开
    document.getElementById('task-panel-header').addEventListener('click', () => {
      _toggleCollapse();
    });

    // 拖拽移动
    _initDrag();

    // 恢复折叠状态
    const savedCollapsed = localStorage.getItem('task_panel_collapsed');
    if (savedCollapsed === 'true') {
      _collapsed = true;
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
  }

  function _toggleCollapse() {
    _collapsed = !_collapsed;
    _panel.classList.toggle('collapsed', _collapsed);
    document.getElementById('task-panel-toggle').textContent = _collapsed ? '▼' : '▲';
    localStorage.setItem('task_panel_collapsed', _collapsed);
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
        startX: e.clientX,
        startY: e.clientY,
      };
      _panel.classList.add('dragging');
    });

    document.addEventListener('mousemove', (e) => {
      if (!_dragState) return;
      const x = e.clientX - _dragState.offsetX;
      const y = e.clientY - _dragState.offsetY;
      _panel.style.left = Math.max(0, x) + 'px';
      _panel.style.top = Math.max(0, y) + 'px';
      _panel.style.right = 'auto';
      _panel.style.bottom = 'auto';
    });

    document.addEventListener('mouseup', () => {
      if (!_dragState) return;
      _panel.classList.remove('dragging');
      // 保存位置（转为 right/bottom 坐标）
      const rect = _panel.getBoundingClientRect();
      const right = window.innerWidth - rect.right;
      const bottom = window.innerHeight - rect.bottom;
      localStorage.setItem('task_panel_pos', JSON.stringify({ right: Math.max(0, right), bottom: Math.max(0, bottom) }));
      _dragState = null;
    });
  }

  // ── 任务追踪 ──

  /**
   * 追踪一个 Celery 任务。
   * @param {string} taskId - Celery task ID
   * @param {string} label - 显示名称（如 "TTS s001"、"批量首帧"）
   * @returns {Promise<object>} - 任务结果
   */
  function trackTask(taskId, label) {
    _init();

    const task = {
      id: taskId,
      label: label || taskId,
      status: 'pending',
      progress: 0,
      message: '等待中...',
      startTime: Date.now(),
      endTime: null,
    };
    _tasks.set(taskId, task);
    _render();
    _ensurePolling();

    return new Promise((resolve) => {
      task._resolve = resolve;
    });
  }

  /** 更新任务状态（供 pollTask 回调使用） */
  function updateTask(taskId, info) {
    const task = _tasks.get(taskId);
    if (!task) return;

    task.progress = info.progress ?? task.progress;
    task.message = info.message || task.message;
    task.status = info.status || task.status;

    if (['success', 'failed', 'cancelled', 'timeout'].includes(info.status)) {
      task.endTime = Date.now();
      if (task._resolve) {
        task._resolve(info);
        task._resolve = null;
      }
    }
    _render();
  }

  /** 主动标记任务完成（外部调用） */
  function completeTask(taskId, status, result) {
    const task = _tasks.get(taskId);
    if (!task) return;

    task.status = status || 'success';
    task.progress = status === 'success' ? 100 : task.progress;
    task.endTime = Date.now();
    if (task._resolve) {
      task._resolve(result || { status });
      task._resolve = null;
    }
    _render();
  }

  /** 取消任务 */
  async function cancelTask(taskId) {
    try {
      await api(`/tasks/${taskId}/cancel`, { method: 'POST' });
      completeTask(taskId, 'cancelled');
    } catch (e) {
      console.error('取消任务失败:', e);
    }
  }

  // ── 轮询 ──

  function _ensurePolling() {
    if (_pollTimer) return;
    _pollLoop();
  }

  async function _pollLoop() {
    const activeIds = [];
    for (const [id, task] of _tasks) {
      if (!['success', 'failed', 'cancelled', 'timeout'].includes(task.status)) {
        activeIds.push(id);
      }
    }

    if (activeIds.length === 0) {
      _pollTimer = null;
      return;
    }

    // 并发轮询所有活跃任务
    await Promise.allSettled(activeIds.map(async (id) => {
      try {
        const info = await api(`/tasks/${id}`);
        updateTask(id, info);
      } catch (e) {
        // 网络错误，下次重试
      }
    }));

    // 清理过期的已完成任务
    _gcCompleted();

    // 继续轮询
    const delay = _calcDelay();
    _pollTimer = setTimeout(_pollLoop, delay);
  }

  function _calcDelay() {
    // 有活跃任务用短间隔，只有已完成的用长间隔
    let hasActive = false;
    for (const task of _tasks.values()) {
      if (!['success', 'failed', 'cancelled', 'timeout'].includes(task.status)) {
        hasActive = true;
        break;
      }
    }
    return hasActive ? POLL_BASE : POLL_MAX;
  }

  function _gcCompleted() {
    const completed = [];
    for (const [id, task] of _tasks) {
      if (['success', 'failed', 'cancelled', 'timeout'].includes(task.status)) {
        completed.push({ id, endTime: task.endTime || 0 });
      }
    }
    if (completed.length > MAX_HISTORY) {
      completed.sort((a, b) => a.endTime - b.endTime);
      const toRemove = completed.slice(0, completed.length - MAX_HISTORY);
      toRemove.forEach(({ id }) => _tasks.delete(id));
    }
  }

  // ── 渲染 ──

  function _render() {
    if (!_body) return;

    const entries = [..._tasks.values()];
    const active = entries.filter(t => !['success', 'failed', 'cancelled', 'timeout'].includes(t.status));
    const done = entries.filter(t => ['success', 'failed', 'cancelled', 'timeout'].includes(t.status))
      .sort((a, b) => (b.endTime || 0) - (a.endTime || 0));

    // 徽章
    _badge.textContent = active.length;
    _badge.style.display = active.length > 0 ? 'inline-flex' : 'none';
    _panel.classList.toggle('has-active', active.length > 0);

    // 自动展开：有新任务时展开
    if (active.length > 0 && _collapsed) {
      _collapsed = false;
      _panel.classList.remove('collapsed');
      document.getElementById('task-panel-toggle').textContent = '▲';
    }

    let html = '';

    // 活跃任务
    for (const t of active) {
      const elapsed = _fmtElapsed(Date.now() - t.startTime);
      const pct = t.progress || 0;
      html += `<div class="task-item task-active">
        <div class="task-item-head">
          <span class="task-item-label">${_esc(t.label)}</span>
          <span class="task-item-elapsed">${elapsed}</span>
        </div>
        <div class="task-item-bar"><div class="task-item-fill" style="width:${pct}%"></div></div>
        <div class="task-item-msg">${_esc(t.message)} (${pct}%)</div>
        <button class="task-item-cancel" onclick="TaskPanel.cancelTask('${t.id}')" title="取消">⏹</button>
      </div>`;
    }

    // 最近完成的任务（最多显示 5 条）
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
    completeTask,
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

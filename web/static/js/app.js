// AI 短剧工作台 v2 — 前端应用（完整版）
// 改进: pollTask 限制、批量取消、删除功能、内联编辑、ESC 关闭、防抖、缓存
const API = '/api';

// ── 缓存层 ──
const _cache = new Map();
const CACHE_TTL = 30000; // 30s

// ── 撤销/重做 ──
const _undoStack = [];  // [{shots: [...], desc: string}]
const _redoStack = [];
const MAX_UNDO = 50;

function pushUndo(desc) {
  _undoStack.push({ shots: JSON.parse(JSON.stringify(shots)), desc });
  if (_undoStack.length > MAX_UNDO) _undoStack.shift();
  _redoStack.length = 0; // 新操作清空重做栈
}

function undo() {
  if (!_undoStack.length) { toast('没有可撤销的操作', 'error'); return; }
  const entry = _undoStack.pop();
  _redoStack.push({ shots: JSON.parse(JSON.stringify(shots)), desc: entry.desc });
  shots = entry.shots;
  invalidateCache(`storyboard/${ep}`);
  api(`/storyboard/${ep}`, { method:'POST', body:{shots} }).then(() => {
    toast(`↩ 撤销: ${entry.desc}`);
    // 刷新当前活跃页面
    const activePage = document.querySelector('.page.active');
    if (activePage?.id === 'page-storyboard') loadStoryboard();
    else renderShotsGrid();
  }).catch(e => toast(e.message, 'error'));
}

function redo() {
  if (!_redoStack.length) { toast('没有可重做的操作', 'error'); return; }
  const entry = _redoStack.pop();
  _undoStack.push({ shots: JSON.parse(JSON.stringify(shots)), desc: entry.desc });
  shots = entry.shots;
  invalidateCache(`storyboard/${ep}`);
  api(`/storyboard/${ep}`, { method:'POST', body:{shots} }).then(() => {
    toast(`↪ 重做: ${entry.desc}`);
    const activePage = document.querySelector('.page.active');
    if (activePage?.id === 'page-storyboard') loadStoryboard();
    else renderShotsGrid();
  }).catch(e => toast(e.message, 'error'));
}

// Ctrl+Z 撤销, Ctrl+Shift+Z 重做
document.addEventListener('keydown', e => {
  if (e.ctrlKey || e.metaKey) {
    if (e.key === 'z' && !e.shiftKey) { e.preventDefault(); undo(); }
    if (e.key === 'z' && e.shiftKey) { e.preventDefault(); redo(); }
    if (e.key === 'y') { e.preventDefault(); redo(); }
  }
});

function cachedFetch(key, fetcher, ttl = CACHE_TTL) {
  const entry = _cache.get(key);
  if (entry && Date.now() - entry.ts < ttl) return Promise.resolve(entry.data);
  return fetcher().then(data => { _cache.set(key, { data, ts: Date.now() }); return data; });
}
function invalidateCache(prefix) {
  for (const k of _cache.keys()) { if (k.startsWith(prefix)) _cache.delete(k); }
}

async function api(path, opts = {}) {
  const r = await fetch(API + path, {
    headers: { 'Content-Type': 'application/json', ...opts.headers },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!r.ok) {
    const t = await r.text();
    try { const j = JSON.parse(t); throw new Error(j.detail || t); } catch(e) { if(e.message) throw e; throw new Error(t); }
  }
  return r.json();
}

function toast(msg, type = 'success') {
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

// ── pollTask: 最多轮询 300 次（约 4 分钟），防止无限等待 ──
const MAX_POLL = 300;

async function pollTask(taskId, onProgress) {
  for (let i = 0; i < MAX_POLL; i++) {
    const info = await api(`/tasks/${taskId}`);
    if (onProgress) onProgress(info);
    if (['success','failed','cancelled'].includes(info.status)) return info;
    await new Promise(r => setTimeout(r, 800));
  }
  return { status: 'timeout', error: '轮询超时，请手动检查任务状态' };
}

// ── 防抖 ──
function debounce(fn, ms = 300) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

// HTML 转义（防 XSS）
function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── 路由 ──
document.querySelectorAll('.nav-item').forEach(item => {
  item.onclick = () => {
    document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    item.classList.add('active');
    document.getElementById(`page-${item.dataset.page}`).classList.add('active');
    loadPage(item.dataset.page);
  };
});
function navTo(p) { document.querySelector(`.nav-item[data-page="${p}"]`).click(); }
async function loadPage(p) {
  const m = { dashboard:loadDashboard, characters:loadCharacters, scenes:loadScenes,
              storyboard:loadStoryboard, pipeline:loadPipeline, projects:loadProjects, settings:loadSettings };
  if (m[p]) await m[p]();
}

// ── ESC 关闭浮层 ──
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    const overlay = document.querySelector('.res-overlay, .edit-overlay');
    if (overlay) overlay.remove();
  }
});

// ══════════════════════════════════════════════════════════
// 仪表盘
// ══════════════════════════════════════════════════════════

const TOOL_META = {
  redis:{icon:'🔴',label:'Redis'}, celery:{icon:'🔧',label:'Celery'}, ffmpeg:{icon:'🎞️',label:'FFmpeg'},
  tts:{icon:'🎤',label:'TTS'}, comfyui:{icon:'🎨',label:'ComfyUI'}, lipsync:{icon:'👄',label:'LipSync'},
  llm:{icon:'🧠',label:'LLM'}, music:{icon:'🎵',label:'配乐'},
};

async function loadDashboard() {
  const el = document.getElementById('page-dashboard');
  try {
    const s = await cachedFetch('system/status', () => api('/system/status'), 10000);
    const t = s.tools;
    const groups = [
      {label:'基础设施', keys:['redis','celery','ffmpeg']},
      {label:'AI 工具', keys:['tts','music']},
      {label:'GPU 工具', keys:['comfyui','lipsync','llm']},
    ];
    let html = '';
    for (const g of groups) {
      html += `<div class="section-label">${g.label}</div><div class="tool-grid">`;
      for (const k of g.keys) {
        const info = t[k]||{}; const meta = TOOL_META[k]||{};
        html += `<div class="tool-card ${info.available?'tool-ok':'tool-off'}">
          <span>${meta.icon} ${meta.label}</span>
          <span class="status-dot ${info.available?'ok':'err'}"></span>
          <span class="dim" style="font-size:0.75rem">${info.available?'可用':info.reason||'不可用'}</span>
        </div>`;
      }
      html += '</div>';
    }
    el.innerHTML = `<div class="card"><h2>📊 系统状态</h2>${html}</div>
      <div class="card"><h2>🚀 开始</h2><p class="dim" style="margin-bottom:0.5rem">进入工作台，选择镜头逐步处理</p>
      <button class="btn btn-primary" onclick="navTo('pipeline')">🎬 进入工作台</button></div>`;
  } catch(e) { el.innerHTML = `<div class="card"><h2>❌ 连接失败</h2><p>${esc(e.message)}</p></div>`; }
}

// ══════════════════════════════════════════════════════════
// 生产工作台
// ══════════════════════════════════════════════════════════

let ep = 1, shots = [], activeShot = 0;
let batchCancelled = false; // 批量取消标志

async function loadPipeline() {
  const el = document.getElementById('page-pipeline');
  el.innerHTML = '<div class="card"><h2>⏳ 加载...</h2></div>';
  try {
    const d = await cachedFetch(`storyboard/${ep}`, () => api(`/storyboard/${ep}`));
    shots = d.shots || [];
    if (!shots.length) {
      el.innerHTML = `<div class="card"><h2>暂无分镜</h2><p class="dim">先在分镜表添加镜头</p>
        <button class="btn btn-primary" style="margin-top:0.5rem" onclick="navTo('storyboard')">去编辑</button></div>`;
      return;
    }
    renderWB();
  } catch(e) { el.innerHTML = `<div class="card"><h2>❌</h2><p>${esc(e.message)}</p></div>`; }
}

function renderWB() {
  const el = document.getElementById('page-pipeline');
  el.innerHTML = `
    <div class="wb-top-bar">
      <h2>🎬 第${ep}集 · ${shots.length} 个镜头</h2>
      <div class="wb-batch-btns">
        <button class="btn btn-outline" onclick="undo()" title="Ctrl+Z">↩ 撤销</button>
        <button class="btn btn-outline" onclick="redo()" title="Ctrl+Shift+Z">↪ 重做</button>
        <button class="btn btn-outline" onclick="batchRun('tts')">🎤 批量 TTS</button>
        <button class="btn btn-outline" onclick="batchRun('first_frame')">🎨 批量首帧</button>
        <button class="btn btn-outline" onclick="batchRun('video')">🎬 批量视频</button>
        <button class="btn btn-outline" onclick="batchRun('lipsync')">👄 批量口型</button>
      </div>
    </div>
    <div id="wb-shots-grid" class="wb-shots-grid"></div>
    <div id="wb-batch-status" class="wb-batch-status" style="display:none"></div>`;
  renderShotsGrid();
}

function renderShotsGrid() {
  const grid = document.getElementById('wb-shots-grid');
  if (!grid) return;
  grid.innerHTML = shots.map((s, i) => {
    const sid = s.shot_id || String(i+1).padStart(3,'0');
    const dlg = (s.dialogue||'').substring(0,20) || '...';
    const act = (s.action||'').substring(0,20) || '...';
    return `<div class="wb-shot-card" id="shot-${sid}">
      <div class="wb-shot-head">
        <span class="wb-shot-num">${sid}</span>
        <span class="wb-shot-char">${s.characters||''}</span>
        <span class="wb-shot-scene">${s.scene||''}</span>
      </div>
      <div class="wb-shot-body">
        <div class="wb-shot-text">
          <div class="wb-shot-action">${act}</div>
          <div class="wb-shot-dialogue">"${dlg}"</div>
        </div>
        <div class="wb-shot-resources" id="res-${sid}"></div>
      </div>
      <div class="wb-shot-actions">
        <button class="btn btn-xs" onclick="editShot(${i})" title="编辑">✏️</button>
        <button class="btn btn-xs" onclick="runOne('tts',${i})" title="TTS">🎤</button>
        <button class="btn btn-xs" onclick="runOne('first_frame',${i})" title="首帧">🎨</button>
        <button class="btn btn-xs" onclick="runOne('video',${i})" title="视频">🎬</button>
        <button class="btn btn-xs" onclick="runOne('lipsync',${i})" title="口型">👄</button>
        <button class="btn btn-xs btn-danger" onclick="deleteShot(${i})" title="删除">🗑️</button>
      </div>
    </div>`;
  }).join('');

  // 批量加载资源（带缓存）
  shots.forEach((s, i) => loadResources(i));
}

async function loadResources(idx) {
  const s = shots[idx];
  const sid = s.shot_id || String(idx+1).padStart(3,'0');
  const el = document.getElementById(`res-${sid}`);
  if (!el) return;

  try {
    const d = await cachedFetch(`res/${ep}/${sid}`, () => api(`/shots/${ep}/${sid}/resources`));
    const r = d.resources || {};
    let html = '';
    if (r.audio) html += `<div class="res-chip res-audio" onclick="previewRes('${sid}','audio','${r.audio}')">🎤</div>`;
    if (r.frame) html += `<div class="res-chip res-img" onclick="previewRes('${sid}','frame','${r.frame}')"><img src="/api/files/${ep}/${sid}/frame.png" loading="lazy"></div>`;
    if (r.video) html += `<div class="res-chip res-video" onclick="previewRes('${sid}','video','${r.video}')">🎬</div>`;
    if (r.synced) html += `<div class="res-chip res-video" onclick="previewRes('${sid}','synced','${r.synced}')">👄</div>`;
    if (!html) html = '<span class="dim" style="font-size:0.7rem">暂无资源</span>';
    el.innerHTML = html;
  } catch {}
}

function previewRes(sid, type, path) {
  const overlay = document.createElement('div');
  overlay.className = 'res-overlay';
  overlay.onclick = () => overlay.remove();

  let content = '';
  if (type === 'audio') {
    content = `<audio controls src="/api/files/${ep}/${sid}/audio.wav" style="width:400px"></audio>`;
  } else if (type === 'frame') {
    content = `<img src="/api/files/${ep}/${sid}/frame.png" style="max-width:90vw;max-height:80vh;border-radius:8px">`;
  } else {
    content = `<video controls src="/api/files/${ep}/${sid}/${type === 'synced' ? 'synced.mp4' : 'video.mp4'}" style="max-width:90vw;max-height:80vh;border-radius:8px"></video>`;
  }
  overlay.innerHTML = `<div class="res-overlay-inner">${content}<div class="dim" style="margin-top:0.5rem">点击空白处关闭 · ESC 键退出</div></div>`;
  document.body.appendChild(overlay);
}

// ── 单镜头编辑 ──

function editShot(idx) {
  activeShot = idx;
  const s = shots[idx];
  const sid = s.shot_id || String(idx+1).padStart(3,'0');

  const overlay = document.createElement('div');
  overlay.className = 'edit-overlay';
  overlay.id = 'edit-overlay';

  overlay.innerHTML = `
    <div class="edit-panel">
      <div class="edit-header">
        <h3>✏️ 编辑镜头 ${sid}</h3>
        <button class="btn btn-sm btn-outline" onclick="closeEdit()">✕</button>
      </div>
      <div class="edit-body">
        <div class="edit-field"><label>场景</label><input id="ed-scene" value="${esc(s.scene||'')}"></div>
        <div class="edit-field"><label>角色</label><input id="ed-chars" value="${esc(s.characters||'')}"></div>
        <div class="edit-field"><label>动作</label><textarea id="ed-action" rows="2">${esc(s.action||'')}</textarea></div>
        <div class="edit-field"><label>台词</label><textarea id="ed-dialogue" rows="2">${esc(s.dialogue||'')}</textarea></div>
        <div class="edit-field-row">
          <div class="edit-field"><label>运镜</label>
            <select id="ed-camera">${['固定','缓慢推近','跟随平移','手持晃动','环绕','俯视','仰视'].map(c=>`<option ${s.camera===c?'selected':''}>${c}</option>`).join('')}</select>
          </div>
          <div class="edit-field"><label>景别</label>
            <select id="ed-shottype">${['特写','近景','中景','过肩','全身','全景','远景'].map(c=>`<option ${s.shot_type===c?'selected':''}>${c}</option>`).join('')}</select>
          </div>
          <div class="edit-field"><label>时长</label><input id="ed-dur" type="number" value="${s.duration||4}" min="1" max="30"></div>
          <div class="edit-field"><label>情绪</label>
            <select id="ed-emo">${['neutral','happy','sad','angry','worried','surprised','calm','determined'].map(c=>`<option ${s.emotion===c?'selected':''}>${c}</option>`).join('')}</select>
          </div>
        </div>
      </div>
      <div class="edit-footer">
        <button class="btn btn-primary" onclick="saveEdit(${idx})">💾 保存</button>
        <button class="btn btn-outline" onclick="closeEdit()">取消</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);

  // 聚焦第一个输入框
  const firstInput = overlay.querySelector('input, textarea');
  if (firstInput) firstInput.focus();
}

function closeEdit() {
  const o = document.getElementById('edit-overlay');
  if (o) o.remove();
}

async function saveEdit(idx) {
  const s = shots[idx];
  s.scene = document.getElementById('ed-scene')?.value || '';
  s.characters = document.getElementById('ed-chars')?.value || '';
  s.action = document.getElementById('ed-action')?.value || '';
  s.dialogue = document.getElementById('ed-dialogue')?.value || '';
  s.camera = document.getElementById('ed-camera')?.value || '';
  s.shot_type = document.getElementById('ed-shottype')?.value || '';
  s.duration = document.getElementById('ed-dur')?.value || 4;
  s.emotion = document.getElementById('ed-emo')?.value || 'neutral';

  pushUndo(`编辑镜头 ${shots[idx].shot_id || idx+1}`);
  try {
    await api(`/storyboard/${ep}`, { method:'POST', body:{shots:shots} });
    invalidateCache(`storyboard/${ep}`);
    invalidateCache(`res/${ep}`);
    toast('✅ 已保存');
    closeEdit();
    renderShotsGrid();
  } catch(e) { toast(e.message, 'error'); }
}

// ── 删除镜头 ──
async function deleteShot(idx) {
  const s = shots[idx];
  const sid = s.shot_id || String(idx+1).padStart(3,'0');
  if (!confirm(t('confirm.delete_shot', {id: sid}))) return;

  pushUndo(`删除镜头 ${sid}`);
  shots.splice(idx, 1);
  try {
    await api(`/storyboard/${ep}`, { method:'POST', body:{shots:shots} });
    invalidateCache(`storyboard/${ep}`);
    toast('✅ 已删除');
    renderShotsGrid();
  } catch(e) { toast(e.message, 'error'); }
}

// ── 单个执行 ──

async function runOne(step, idx) {
  const s = shots[idx];
  const sid = s.shot_id || String(idx+1).padStart(3,'0');

  const card = document.getElementById(`shot-${sid}`);
  const actionsEl = card?.querySelector('.wb-shot-actions');
  if (actionsEl) actionsEl.innerHTML = `<span class="run-indicator">⏳ ${step}...</span>`;

  try {
    const r = await fetch(`${API}/steps/${step}`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({episode:ep, shot_id:sid}),
    });
    if (!r.ok) { const t = await r.text(); throw new Error(t); }
    const data = await r.json();

    const result = await pollTask(data.task_id, (info) => {
      if (actionsEl) actionsEl.innerHTML = `<span class="run-indicator">⏳ ${info.message||step} (${info.progress||0}%)</span>`;
    });

    if (result.status === 'success') {
      toast(`✅ ${sid} ${step} 完成`);
    } else if (result.status === 'timeout') {
      toast(`⏰ ${sid} ${step}: 轮询超时`, 'error');
    } else {
      toast(`❌ ${sid} ${step}: ${result.error||'失败'}`, 'error');
    }
  } catch(e) {
    toast(`❌ ${sid}: ${e.message}`, 'error');
  }

  // 恢复按钮 + 刷新资源
  if (actionsEl) {
    actionsEl.innerHTML = `
      <button class="btn btn-xs" onclick="editShot(${idx})" title="编辑">✏️</button>
      <button class="btn btn-xs" onclick="runOne('tts',${idx})" title="TTS">🎤</button>
      <button class="btn btn-xs" onclick="runOne('first_frame',${idx})" title="首帧">🎨</button>
      <button class="btn btn-xs" onclick="runOne('video',${idx})" title="视频">🎬</button>
      <button class="btn btn-xs" onclick="runOne('lipsync',${idx})" title="口型">👄</button>
      <button class="btn btn-xs btn-danger" onclick="deleteShot(${idx})" title="删除">🗑️</button>`;
  }
  invalidateCache(`res/${ep}/${sid}`);
  loadResources(idx);
}

// ── 批量执行（带取消按钮）──

async function batchRun(step) {
  const names = {tts:'TTS',first_frame:'首帧',video:'视频',lipsync:'口型同步'};
  if (!confirm(`批量执行 ${names[step]}？共 ${shots.length} 个镜头`)) return;

  batchCancelled = false;
  const statusEl = document.getElementById('wb-batch-status');
  statusEl.style.display = 'block';

  let done = 0, fail = 0, skip = 0;
  for (let i = 0; i < shots.length; i++) {
    // 检查取消
    if (batchCancelled) {
      statusEl.innerHTML = `<div class="batch-done">⏹ 已取消 · ✅ ${done} · ⏭ ${skip} · ❌ ${fail}
        <button class="btn btn-sm btn-outline" style="margin-left:0.5rem" onclick="this.parentElement.parentElement.style.display='none'">关闭</button></div>`;
      toast(`批量已取消: ${done}成功 ${skip}跳过 ${fail}失败`);
      return;
    }

    const s = shots[i];
    const sid = s.shot_id || String(i+1).padStart(3,'0');

    statusEl.innerHTML = `
      <div class="batch-progress">
        <div class="batch-bar"><div class="batch-fill" style="width:${(i/shots.length)*100}%"></div></div>
        <div class="batch-text">[${i+1}/${shots.length}] ${sid} — ${names[step]}...</div>
        <button class="btn btn-sm btn-danger" onclick="batchCancelled=true" style="margin-top:0.3rem">⏹ 取消</button>
      </div>`;

    try {
      const r = await fetch(`${API}/steps/${step}`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({episode:ep, shot_id:sid}),
      });
      if (!r.ok) { fail++; continue; }
      const data = await r.json();
      const result = await pollTask(data.task_id);
      if (result.status === 'success') { done++; invalidateCache(`res/${ep}/${sid}`); loadResources(i); }
      else if (result.result?.status === 'skipped') { skip++; }
      else { fail++; }
    } catch { fail++; }
  }

  statusEl.innerHTML = `
    <div class="batch-done">
      ✅ 完成 ${done} · ⏭ 跳过 ${skip} · ❌ 失败 ${fail}
      <button class="btn btn-sm btn-outline" style="margin-left:0.5rem" onclick="this.parentElement.parentElement.style.display='none'">关闭</button>
    </div>`;
  toast(`批量完成: ${done}成功 ${skip}跳过 ${fail}失败`);
}

// ══════════════════════════════════════════════════════════
// 角色管理 — 内联编辑 + 删除
// ══════════════════════════════════════════════════════════

async function loadCharacters() {
  const el = document.getElementById('page-characters');
  try {
    const d = await cachedFetch('characters', () => api('/characters'));
    let rows = (d.characters||[]).map(c => `
      <tr>
        <td>${c.id}</td><td>${c.name}</td><td>${c.gender||''}</td>
        <td>${(c.appearance||'').substring(0,40)}</td>
        <td>
          <button class="btn btn-xs" onclick="editChar('${c.id}')">✏️</button>
          <button class="btn btn-xs btn-danger" onclick="deleteChar('${c.id}')">🗑️</button>
        </td>
      </tr>`).join('');
    el.innerHTML = `<div class="card"><div style="display:flex;justify-content:space-between;margin-bottom:1rem"><h2>👤 角色</h2><button class="btn btn-success" onclick="newChar()">+ 新建</button></div>
      <table><thead><tr><th>ID</th><th>姓名</th><th>性别</th><th>外观</th><th>操作</th></tr></thead><tbody>${rows||'<tr><td colspan="5" class="dim" style="text-align:center">暂无</td></tr>'}</tbody></table></div>`;
  } catch(e) { el.innerHTML = `<div class="card"><h2>❌</h2><p>${esc(e.message)}</p></div>`; }
}

async function newChar() {
  const id = prompt('ID (字母数字下划线):');
  if (!id) return;
  if (!/^[a-zA-Z0-9_-]+$/.test(id)) { toast('ID 格式不合法', 'error'); return; }
  const name = prompt('姓名:');
  if (!name) return;
  try {
    await api('/characters', {method:'POST', body:{id, name, gender:'', appearance:'', outfits:{}, voice:{}}});
    invalidateCache('characters');
    toast('已创建');
    loadCharacters();
  } catch(e) { toast(e.message, 'error'); }
}

async function editChar(id) {
  const d = await cachedFetch('characters', () => api('/characters'));
  const c = (d.characters||[]).find(x => x.id === id);
  if (!c) { toast('角色不存在', 'error'); return; }

  const overlay = document.createElement('div');
  overlay.className = 'edit-overlay';
  overlay.id = 'edit-char-overlay';
  overlay.innerHTML = `
    <div class="edit-panel">
      <div class="edit-header"><h3>✏️ 编辑角色 ${id}</h3><button class="btn btn-sm btn-outline" onclick="document.getElementById('edit-char-overlay').remove()">✕</button></div>
      <div class="edit-body">
        <div class="edit-field"><label>姓名</label><input id="ec-name" value="${esc(c.name||'')}"></div>
        <div class="edit-field"><label>性别</label><select id="ec-gender"><option value="">-</option><option value="male" ${c.gender==='male'?'selected':''}>男</option><option value="female" ${c.gender==='female'?'selected':''}>女</option></select></div>
        <div class="edit-field"><label>外观</label><textarea id="ec-appearance" rows="3">${esc(c.appearance||'')}</textarea></div>
      </div>
      <div class="edit-footer">
        <button class="btn btn-primary" onclick="saveCharEdit('${id}')">💾 保存</button>
        <button class="btn btn-outline" onclick="document.getElementById('edit-char-overlay').remove()">取消</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
}

async function saveCharEdit(id) {
  try {
    await api('/characters', {method:'POST', body:{
      id,
      name: document.getElementById('ec-name').value,
      gender: document.getElementById('ec-gender').value,
      appearance: document.getElementById('ec-appearance').value,
    }});
    invalidateCache('characters');
    document.getElementById('edit-char-overlay')?.remove();
    toast('✅ 已保存');
    loadCharacters();
  } catch(e) { toast(e.message, 'error'); }
}

async function deleteChar(id) {
  if (!confirm(`确认删除角色 ${id}？`)) return;
  try {
    await api(`/characters/${id}`, {method:'DELETE'});
    invalidateCache('characters');
    toast('✅ 已删除');
    loadCharacters();
  } catch(e) { toast(e.message, 'error'); }
}

// ══════════════════════════════════════════════════════════
// 场景管理 — 内联编辑 + 删除
// ══════════════════════════════════════════════════════════

async function loadScenes() {
  const el = document.getElementById('page-scenes');
  try {
    const d = await cachedFetch('scenes', () => api('/scenes'));
    let rows = (d.scenes||[]).map(s => `
      <tr>
        <td>${s.id}</td><td>${s.name}</td><td>${(s.description||'').substring(0,40)}</td>
        <td>
          <button class="btn btn-xs" onclick="editScene('${s.id}')">✏️</button>
          <button class="btn btn-xs btn-danger" onclick="deleteScene('${s.id}')">🗑️</button>
        </td>
      </tr>`).join('');
    el.innerHTML = `<div class="card"><div style="display:flex;justify-content:space-between;margin-bottom:1rem"><h2>🏔️ 场景</h2><button class="btn btn-success" onclick="newScene()">+ 新建</button></div>
      <table><thead><tr><th>ID</th><th>名称</th><th>描述</th><th>操作</th></tr></thead><tbody>${rows||'<tr><td colspan="4" class="dim" style="text-align:center">暂无</td></tr>'}</tbody></table></div>`;
  } catch(e) { el.innerHTML = `<div class="card"><h2>❌</h2><p>${esc(e.message)}</p></div>`; }
}

async function newScene() {
  const id = prompt('ID (字母数字下划线):');
  if (!id) return;
  if (!/^[a-zA-Z0-9_-]+$/.test(id)) { toast('ID 格式不合法', 'error'); return; }
  const name = prompt('名称:');
  if (!name) return;
  try {
    await api('/scenes', {method:'POST', body:{id, name, description:'', lighting:''}});
    invalidateCache('scenes');
    toast('已创建');
    loadScenes();
  } catch(e) { toast(e.message, 'error'); }
}

async function editScene(id) {
  const d = await cachedFetch('scenes', () => api('/scenes'));
  const s = (d.scenes||[]).find(x => x.id === id);
  if (!s) { toast('场景不存在', 'error'); return; }

  const overlay = document.createElement('div');
  overlay.className = 'edit-overlay';
  overlay.id = 'edit-scene-overlay';
  overlay.innerHTML = `
    <div class="edit-panel">
      <div class="edit-header"><h3>✏️ 编辑场景 ${id}</h3><button class="btn btn-sm btn-outline" onclick="document.getElementById('edit-scene-overlay').remove()">✕</button></div>
      <div class="edit-body">
        <div class="edit-field"><label>名称</label><input id="es-name" value="${esc(s.name||'')}"></div>
        <div class="edit-field"><label>描述</label><textarea id="es-desc" rows="3">${esc(s.description||'')}</textarea></div>
        <div class="edit-field"><label>光照</label><input id="es-lighting" value="${esc(s.lighting||'')}"></div>
      </div>
      <div class="edit-footer">
        <button class="btn btn-primary" onclick="saveSceneEdit('${id}')">💾 保存</button>
        <button class="btn btn-outline" onclick="document.getElementById('edit-scene-overlay').remove()">取消</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
}

async function saveSceneEdit(id) {
  try {
    await api('/scenes', {method:'POST', body:{
      id,
      name: document.getElementById('es-name').value,
      description: document.getElementById('es-desc').value,
      lighting: document.getElementById('es-lighting').value,
    }});
    invalidateCache('scenes');
    document.getElementById('edit-scene-overlay')?.remove();
    toast('✅ 已保存');
    loadScenes();
  } catch(e) { toast(e.message, 'error'); }
}

async function deleteScene(id) {
  if (!confirm(`确认删除场景 ${id}？`)) return;
  try {
    await api(`/scenes/${id}`, {method:'DELETE'});
    invalidateCache('scenes');
    toast('✅ 已删除');
    loadScenes();
  } catch(e) { toast(e.message, 'error'); }
}

// ══════════════════════════════════════════════════════════
// 分镜表 — 内联编辑表格
// ══════════════════════════════════════════════════════════

async function loadStoryboard() {
  const el = document.getElementById('page-storyboard');
  try {
    const d = await cachedFetch(`storyboard/${ep}`, () => api(`/storyboard/${ep}`));
    const shots = d.shots || [];
    let rows = shots.map((s, i) => {
      const sid = s.shot_id || String(i+1).padStart(3,'0');
      return `<tr>
        <td>${sid}</td>
        <td><input class="sb-inline-input" value="${esc(s.scene||'')}" data-idx="${i}" data-field="scene" onchange="updateShotField(this)"></td>
        <td><input class="sb-inline-input" value="${esc(s.characters||'')}" data-idx="${i}" data-field="characters" onchange="updateShotField(this)"></td>
        <td><input class="sb-inline-input" value="${esc(s.action||'')}" data-idx="${i}" data-field="action" onchange="updateShotField(this)"></td>
        <td><input class="sb-inline-input" value="${esc(s.dialogue||'')}" data-idx="${i}" data-field="dialogue" onchange="updateShotField(this)"></td>
        <td><select class="sb-inline-input" data-idx="${i}" data-field="camera" onchange="updateShotField(this)">
          ${['固定','缓慢推近','跟随平移','手持晃动','环绕','俯视','仰视'].map(c=>`<option ${s.camera===c?'selected':''}>${c}</option>`).join('')}
        </select></td>
        <td><select class="sb-inline-input" data-idx="${i}" data-field="shot_type" onchange="updateShotField(this)">
          ${['特写','近景','中景','过肩','全身','全景','远景'].map(c=>`<option ${s.shot_type===c?'selected':''}>${c}</option>`).join('')}
        </select></td>
        <td><input class="sb-inline-input" type="number" value="${s.duration||4}" min="1" max="30" data-idx="${i}" data-field="duration" onchange="updateShotField(this)"></td>
        <td><button class="btn btn-xs btn-danger" onclick="deleteShotFromSB(${i})">🗑️</button></td>
      </tr>`;
    }).join('');
    el.innerHTML = `<div class="card"><div style="display:flex;justify-content:space-between;margin-bottom:1rem"><h2>📝 分镜表</h2><div><button class="btn btn-primary" onclick="navTo('pipeline')">🎬 工作台</button><button class="btn btn-success" style="margin-left:0.5rem" onclick="addShot()">+ 添加</button></div></div>
      <div style="overflow-x:auto"><table><thead><tr><th>镜号</th><th>场景</th><th>角色</th><th>动作</th><th>台词</th><th>运镜</th><th>景别</th><th>时长</th><th></th></tr></thead><tbody>${rows||'<tr><td colspan="9" class="dim" style="text-align:center">暂无</td></tr>'}</tbody></table></div></div>`;
  } catch(e) { el.innerHTML = `<div class="card"><h2>❌</h2><p>${esc(e.message)}</p></div>`; }
}

// 内联编辑更新（防抖批量保存）
let _sbDirty = false;
const _debouncedSaveSB = debounce(async () => {
  if (!_sbDirty) return;
  try {
    const d = await api(`/storyboard/${ep}`);
    const currentShots = d.shots || [];
    // 从 DOM 读取最新值
    document.querySelectorAll('.sb-inline-input').forEach(inp => {
      const idx = parseInt(inp.dataset.idx);
      const field = inp.dataset.field;
      if (currentShots[idx]) {
        currentShots[idx][field] = inp.value;
      }
    });
    await api(`/storyboard/${ep}`, { method:'POST', body:{shots:currentShots} });
    invalidateCache(`storyboard/${ep}`);
    _sbDirty = false;
    toast('✅ 已保存');
  } catch(e) { toast(e.message, 'error'); }
}, 1000);

function updateShotField(el) {
  _sbDirty = true;
  _debouncedSaveSB();
}

async function deleteShotFromSB(idx) {
  if (!confirm('确认删除此镜头？')) return;
  try {
    const d = await api(`/storyboard/${ep}`);
    const currentShots = d.shots || [];
    pushUndo(`删除镜头 ${currentShots[idx]?.shot_id || idx+1}`);
    currentShots.splice(idx, 1);
    await api(`/storyboard/${ep}`, { method:'POST', body:{shots:currentShots} });
    invalidateCache(`storyboard/${ep}`);
    toast('✅ 已删除');
    loadStoryboard();
  } catch(e) { toast(e.message, 'error'); }
}

async function addShot() {
  try {
    const d = await api(`/storyboard/${ep}`);
    const existing = d.shots || [];
    // 找最大 shot_id 数字部分，避免删除后 ID 冲突
    let maxNum = 0;
    for (const s of existing) {
      const num = parseInt(s.shot_id, 10);
      if (!isNaN(num) && num > maxNum) maxNum = num;
    }
    const newId = String(maxNum + 1).padStart(3, '0');
    pushUndo(`添加镜头 ${newId}`);
    await api(`/storyboard/${ep}`, {method:'POST', body:{shots:[
      ...existing,
      {episode:ep, shot_id:newId,scene:'',characters:'',action:'',dialogue:'......',camera:'固定',shot_type:'中景',duration:4,emotion:'neutral',outfit:'',action_en:'',dialogue_en:''}
    ]}});
    invalidateCache(`storyboard/${ep}`);
    toast('已添加');
    loadStoryboard();
  } catch(e) { toast(e.message, 'error'); }
}

// ══════════════════════════════════════════════════════════
// 项目管理
// ══════════════════════════════════════════════════════════

async function loadProjects() {
  const el = document.getElementById('page-projects');
  try {
    const d = await api('/projects');
    let rows = (d.projects||[]).map(p=>`<tr><td>${p.active?'→':''}</td><td>${p.name}</td><td class="dim" style="font-size:0.75rem">${p.path}</td><td>${p.active?'<span class="badge badge-green">当前</span>':`<button class="btn btn-sm btn-primary" onclick="switchProj('${p.name}')">切换</button>`}</td></tr>`).join('');
    el.innerHTML = `<div class="card"><div style="display:flex;justify-content:space-between;margin-bottom:1rem"><h2>📂 项目</h2><button class="btn btn-success" onclick="newProj()">+ 新建</button></div>
      <table><thead><tr><th></th><th>名称</th><th>路径</th><th>状态</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  } catch(e) { el.innerHTML = `<div class="card"><h2>❌</h2><p>${esc(e.message)}</p></div>`; }
}
function newProj() { const n=prompt('名称:'); if(!n) return; api('/projects/new',{method:'POST',body:{name:n}}).then(()=>{toast('已创建');loadProjects();}).catch(e=>toast(e.message,'error')); }
function switchProj(n) { api('/projects/switch',{method:'POST',body:{name:n}}).then(()=>{toast(`已切换: ${n}`);loadProjects();}).catch(e=>toast(e.message,'error')); }

// ══════════════════════════════════════════════════════════
// 系统设置
// ══════════════════════════════════════════════════════════

async function loadSettings() {
  const el = document.getElementById('page-settings');
  try {
    const [cfg,env,td] = await Promise.all([api('/config'),api('/system/env'),api('/tools')]);
    _cache.set('config', {data: cfg, ts: Date.now()}); // 缓存配置供后端切换使用
    const t_tools = td.tools||{};
    const currentLang = localStorage.getItem('drama_lang') || 'zh';
    el.innerHTML = `
      <div class="card"><h2>🌐 语言 / Language</h2>
        <div class="form-row"><label>界面语言</label>
          <select id="cfg-lang" onchange="setLang(this.value);loadSettings()">
            <option value="zh" ${currentLang==='zh'?'selected':''}>中文</option>
            <option value="en" ${currentLang==='en'?'selected':''}>English</option>
          </select>
        </div>
      </div>
      <div class="card"><h2>💻 环境</h2><div class="info-grid"><div><span class="dim">OS:</span> ${env.os}</div><div><span class="dim">Python:</span> ${env.python}</div><div><span class="dim">GPU:</span> ${env.gpu.available?env.gpu.name+' ('+env.gpu.vram_mb+'MB)':'不可用'}</div></div></div>
      <div class="card"><h2>🔧 配置</h2>
        <div class="config-section"><h3>🎤 TTS</h3>
          <div class="form-row"><label>后端</label><select id="cfg-tts" onchange="updateTtsUrl()">${['mimo-voicedesign','mimo-voiceclone','gpt-sovits','cosyvoice','fish-speech'].map(b=>`<option value="${b}" ${cfg.models?.tts_backend===b?'selected':''}>${b}</option>`).join('')}</select></div>
          <div class="form-row"><label>地址</label><input id="cfg-tts-url" value="${cfg.models?.[document.getElementById('cfg-tts')?.value?.replace(/-/g,'_')]?.api_url||cfg.models?.gpt_sovits?.api_url||''}"></div>
          <div class="tool-status-inline"><span class="status-dot ${t_tools.tts?.available?'ok':'err'}"></span>${t_tools.tts?.available?'可用':t_tools.tts?.reason||'不可用'}</div>
        </div>
        <div class="config-section"><h3>🎨 ComfyUI</h3>
          <div class="form-row"><label>地址</label><input id="cfg-comfyui" value="${cfg.comfyui?.url||''}"></div>
          <div class="tool-status-inline"><span class="status-dot ${t_tools.comfyui?.available?'ok':'err'}"></span>${t_tools.comfyui?.available?'可用':t_tools.comfyui?.reason||'不可用'}</div>
        </div>
        <div class="config-section"><h3>👄 LipSync</h3>
          <div class="form-row"><label>后端</label><select id="cfg-lipsync" onchange="updateLsUrl()">${['musetalk','sadtalker','wav2lip'].map(b=>`<option value="${b}" ${cfg.models?.lip_sync_backend===b?'selected':''}>${b}</option>`).join('')}</select></div>
          <div class="form-row"><label>地址</label><input id="cfg-ls-url" value="${cfg.models?.[document.getElementById('cfg-lipsync')?.value?.replace(/-/g,'_')]?.api_url||cfg.models?.musetalk?.api_url||''}"></div>
          <div class="tool-status-inline"><span class="status-dot ${t_tools.lipsync?.available?'ok':'err'}"></span>${t_tools.lipsync?.available?'可用':t_tools.lipsync?.reason||'不可用'}</div>
        </div>
        <button class="btn btn-primary" style="margin-top:1rem" onclick="saveCfg()">💾 保存</button>
      </div>`;
  } catch(e) { el.innerHTML = `<div class="card"><h2>❌</h2><p>${esc(e.message)}</p></div>`; }
}
async function saveCfg() {
  try {
    const cfg = await api('/config');
    cfg.models=cfg.models||{};
    const ttsBackend = document.getElementById('cfg-tts')?.value;
    cfg.models.tts_backend = ttsBackend;
    cfg.models.lip_sync_backend=document.getElementById('cfg-lipsync')?.value;
    // 保存 TTS URL 到对应后端配置
    const ttsKey = ttsBackend?.replace(/-/g, '_');
    if (ttsKey) {
      cfg.models[ttsKey] = cfg.models[ttsKey]||{};
      cfg.models[ttsKey].api_url = document.getElementById('cfg-tts-url')?.value||'';
    }
    const lsBackend = document.getElementById('cfg-lipsync')?.value;
    const lsKey = lsBackend?.replace(/-/g, '_');
    if (lsKey) {
      cfg.models[lsKey] = cfg.models[lsKey]||{};
      cfg.models[lsKey].api_url = document.getElementById('cfg-ls-url')?.value||'';
    }
    cfg.comfyui=cfg.comfyui||{}; cfg.comfyui.url=document.getElementById('cfg-comfyui')?.value||'';
    await api('/config',{method:'POST',body:cfg}); toast('✅ 已保存');
  } catch(e) { toast(e.message, 'error'); }
}

// TTS 后端切换时更新 URL
function updateTtsUrl() {
  const backend = document.getElementById('cfg-tts')?.value;
  const key = backend?.replace(/-/g, '_');
  // 从缓存的配置中读取对应后端的 URL
  const entry = _cache.get('config');
  const cfg = entry?.data || {};
  const url = cfg.models?.[key]?.api_url || '';
  const urlInput = document.getElementById('cfg-tts-url');
  if (urlInput) urlInput.value = url;
}

// LipSync 后端切换时更新 URL
function updateLsUrl() {
  const backend = document.getElementById('cfg-lipsync')?.value;
  const key = backend?.replace(/-/g, '_');
  const entry = _cache.get('config');
  const cfg = entry?.data || {};
  const url = cfg.models?.[key]?.api_url || '';
  const urlInput = document.getElementById('cfg-ls-url');
  if (urlInput) urlInput.value = url;
}

loadDashboard();

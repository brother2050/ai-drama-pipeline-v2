// AI 短剧工作台 v2
const API = '/api';

// ── 基础设施 ──

const _cache = new Map();
const CACHE_TTL = 30000;
const MAX_UNDO = 50;
const MAX_POLL = 300;

let ep = 1, shots = [], activeShot = 0, batchCancelled = false;
const _undoStack = [], _redoStack = [];

function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function debounce(fn, ms = 300) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
function toast(msg, type = 'success') { const el = document.createElement('div'); el.className = `toast toast-${type}`; el.textContent = msg; document.body.appendChild(el); setTimeout(() => el.remove(), 3500); }

function cachedFetch(key, fetcher, ttl = CACHE_TTL) {
  const e = _cache.get(key);
  if (e && Date.now() - e.ts < ttl) return Promise.resolve(e.data);
  return fetcher().then(d => { _cache.set(key, { data: d, ts: Date.now() }); return d; });
}
function invalidateCache(prefix) { for (const k of _cache.keys()) if (k.startsWith(prefix)) _cache.delete(k); }

async function api(path, opts = {}) {
  const { body, headers, ...rest } = opts;
  const r = await fetch(API + path, {
    headers: { 'Content-Type': 'application/json', ...headers }, ...rest,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    const raw = await r.text();
    try { const j = JSON.parse(raw); throw new Error(j.detail || raw); } catch (e) { if (e.message) throw e; throw new Error(raw); }
  }
  return r.json();
}

async function pollTask(taskId, onProgress) {
  for (let i = 0; i < MAX_POLL; i++) {
    const info = await api(`/tasks/${taskId}`);
    if (onProgress) onProgress(info);
    if (['success', 'failed', 'cancelled'].includes(info.status)) return info;
    await new Promise(r => setTimeout(r, 800));
  }
  return { status: 'timeout', error: '轮询超时' };
}

// ── 撤销/重做 ──

function _applyHistory(from, to, label) {
  if (!from.length) { toast(`没有可${label}的操作`, 'error'); return; }
  const entry = from.pop();
  to.push({ shots: JSON.parse(JSON.stringify(shots)), desc: entry.desc });
  shots = entry.shots;
  invalidateCache(`storyboard/${ep}`);
  api(`/storyboard/${ep}`, { method: 'POST', body: { shots } }).then(() => {
    toast(`${label === '撤销' ? '↩' : '↪'} ${label}: ${entry.desc}`);
    const p = document.querySelector('.page.active');
    p?.id === 'page-storyboard' ? loadStoryboard() : renderShotsGrid();
  }).catch(e => toast(e.message, 'error'));
}
function pushUndo(desc) { _undoStack.push({ shots: JSON.parse(JSON.stringify(shots)), desc }); if (_undoStack.length > MAX_UNDO) _undoStack.shift(); _redoStack.length = 0; }
function undo() { _applyHistory(_undoStack, _redoStack, '撤销'); }
function redo() { _applyHistory(_redoStack, _undoStack, '重做'); }

// ── 路由 ──

document.querySelectorAll('.nav-item').forEach(item => {
  item.onclick = () => {
    document.querySelectorAll('.nav-item,.page').forEach(el => el.classList.remove('active'));
    item.classList.add('active');
    document.getElementById(`page-${item.dataset.page}`).classList.add('active');
    loadPage(item.dataset.page);
  };
});
function navTo(p) { document.querySelector(`.nav-item[data-page="${p}"]`).click(); }
const PAGES = { dashboard: loadDashboard, characters: loadCharacters, scenes: loadScenes, storyboard: loadStoryboard, pipeline: loadPipeline, projects: loadProjects, settings: loadSettings };
async function loadPage(p) { if (PAGES[p]) await PAGES[p](); }

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') document.querySelector('.res-overlay, .edit-overlay')?.remove();
  if (e.ctrlKey || e.metaKey) {
    if (e.key === 'z' && !e.shiftKey) { e.preventDefault(); undo(); }
    if ((e.key === 'z' && e.shiftKey) || e.key === 'y') { e.preventDefault(); redo(); }
  }
});

// ══════════════════════════════════════════════════════════
// 通用 CRUD
// ══════════════════════════════════════════════════════════

function _crudTable(cols, items, editFn, delFn) {
  const ths = cols.map(c => `<th>${c.label}</th>`).join('') + '<th>操作</th>';
  const rows = items.length
    ? items.map(it => {
      const tds = cols.map(c => `<td>${c.render ? c.render(it) : esc(it[c.key] || '')}</td>`).join('');
      return `<tr>${tds}<td><button class="btn btn-xs" onclick="${editFn}('${it.id}')">✏️</button>
        <button class="btn btn-xs btn-danger" onclick="${delFn}('${it.id}')">🗑️</button></td></tr>`;
    }).join('')
    : `<tr><td colspan="${cols.length + 1}" class="dim" style="text-align:center">暂无</td></tr>`;
  return `<table><thead><tr>${ths}</tr></thead><tbody>${rows}</tbody></table>`;
}

function _crudPage(title, cols, items, editFn, delFn, newFn) {
  return `<div class="card"><div style="display:flex;justify-content:space-between;margin-bottom:1rem">
    <h2>${title}</h2><button class="btn btn-success" onclick="${newFn}()">+ 新建</button></div>${_crudTable(cols, items, editFn, delFn)}</div>`;
}

async function _crudCreate(endpoint, extra, reload) {
  const id = prompt('ID (字母数字下划线):'); if (!id) return;
  if (!/^[a-zA-Z0-9_-]+$/.test(id)) { toast('ID 格式不合法', 'error'); return; }
  const name = prompt('名称:'); if (!name) return;
  try { await api(`/${endpoint}`, { method: 'POST', body: { id, name, ...extra } }); invalidateCache(endpoint); toast('已创建'); reload(); } catch (e) { toast(e.message, 'error'); }
}
async function _crudDelete(endpoint, id, label, reload) {
  if (!confirm(`确认删除${label} ${id}？`)) return;
  try { await api(`/${endpoint}/${id}`, { method: 'DELETE' }); invalidateCache(endpoint); toast('✅ 已删除'); reload(); } catch (e) { toast(e.message, 'error'); }
}
async function _crudSave(endpoint, id, fieldsFn, overlayId, reload) {
  try { await api(`/${endpoint}`, { method: 'POST', body: { id, ...fieldsFn() } }); invalidateCache(endpoint); document.getElementById(overlayId)?.remove(); toast('✅ 已保存'); reload(); } catch (e) { toast(e.message, 'error'); }
}

function _showOverlay(id, title, bodyHtml, saveFn) {
  const o = document.createElement('div'); o.className = 'edit-overlay'; o.id = id;
  o.innerHTML = `<div class="edit-panel"><div class="edit-header"><h3>${title}</h3>
    <button class="btn btn-sm btn-outline" onclick="document.getElementById('${id}')?.remove()">✕</button></div>
    <div class="edit-body">${bodyHtml}</div><div class="edit-footer">
    <button class="btn btn-primary" onclick="${saveFn}">💾 保存</button>
    <button class="btn btn-outline" onclick="document.getElementById('${id}')?.remove()">取消</button></div></div>`;
  document.body.appendChild(o);
  o.querySelector('input,textarea')?.focus();
}

// ══════════════════════════════════════════════════════════
// 仪表盘
// ══════════════════════════════════════════════════════════

const TOOL_META = { redis:{icon:'🔴',label:'Redis'}, celery:{icon:'🔧',label:'Celery'}, ffmpeg:{icon:'🎞️',label:'FFmpeg'}, tts:{icon:'🎤',label:'TTS'}, comfyui:{icon:'🎨',label:'ComfyUI'}, lipsync:{icon:'👄',label:'LipSync'}, llm:{icon:'🧠',label:'LLM'}, music:{icon:'🎵',label:'配乐'} };

async function loadDashboard() {
  const el = document.getElementById('page-dashboard');
  try {
    const s = await cachedFetch('system/status', () => api('/system/status'), 10000);
    const groups = [
      { label: '基础设施', keys: ['redis', 'celery', 'ffmpeg'] },
      { label: 'AI 工具', keys: ['tts', 'music'] },
      { label: 'GPU 工具', keys: ['comfyui', 'lipsync', 'llm'] },
    ];
    let html = '';
    for (const g of groups) {
      html += `<div class="section-label">${g.label}</div><div class="tool-grid">`;
      for (const k of g.keys) {
        const info = s.tools[k] || {}, meta = TOOL_META[k] || {};
        html += `<div class="tool-card ${info.available ? 'tool-ok' : 'tool-off'}"><span>${meta.icon} ${meta.label}</span>
          <span class="status-dot ${info.available ? 'ok' : 'err'}"></span>
          <span class="dim" style="font-size:0.75rem">${info.available ? '可用' : info.reason || '不可用'}</span></div>`;
      }
      html += '</div>';
    }
    el.innerHTML = `<div class="card"><h2>📊 系统状态</h2>${html}</div>
      <div class="card"><h2>🚀 开始</h2><p class="dim" style="margin-bottom:0.5rem">进入工作台，选择镜头逐步处理</p>
      <button class="btn btn-primary" onclick="navTo('pipeline')">🎬 进入工作台</button></div>`;
  } catch (e) { el.innerHTML = `<div class="card"><h2>❌ 连接失败</h2><p>${esc(e.message)}</p></div>`; }
}

// ══════════════════════════════════════════════════════════
// 生产工作台
// ══════════════════════════════════════════════════════════

const STEP_BTNS = [
  { step: 'tts', icon: '🎤', label: 'TTS' },
  { step: 'first_frame', icon: '🎨', label: '首帧' },
  { step: 'video', icon: '🎬', label: '视频' },
  { step: 'lipsync', icon: '👄', label: '口型' },
];

function _shotId(s, i) { return s.shot_id || String(i + 1).padStart(3, '0'); }
function _actionBtns(idx) {
  return `<button class="btn btn-xs" onclick="editShot(${idx})" title="编辑">✏️</button>` +
    STEP_BTNS.map(b => `<button class="btn btn-xs" onclick="runOne('${b.step}',${idx})" title="${b.label}">${b.icon}</button>`).join('') +
    `<button class="btn btn-xs btn-danger" onclick="deleteShot(${idx})" title="删除">🗑️</button>`;
}

async function loadPipeline() {
  const el = document.getElementById('page-pipeline');
  el.innerHTML = '<div class="card"><h2>⏳ 加载...</h2></div>';
  try {
    const d = await cachedFetch(`storyboard/${ep}`, () => api(`/storyboard/${ep}`));
    shots = d.shots || [];
    if (!shots.length) { el.innerHTML = `<div class="card"><h2>暂无分镜</h2><p class="dim">先在分镜表添加镜头</p><button class="btn btn-primary" style="margin-top:0.5rem" onclick="navTo('storyboard')">去编辑</button></div>`; return; }
    renderWB();
  } catch (e) { el.innerHTML = `<div class="card"><h2>❌</h2><p>${esc(e.message)}</p></div>`; }
}

function renderWB() {
  const el = document.getElementById('page-pipeline');
  el.innerHTML = `<div class="wb-top-bar"><h2>🎬 第${ep}集 · ${shots.length} 个镜头</h2>
    <div class="wb-batch-btns">
      <button class="btn btn-outline" onclick="undo()" title="Ctrl+Z">↩ 撤销</button>
      <button class="btn btn-outline" onclick="redo()" title="Ctrl+Shift+Z">↪ 重做</button>
      ${STEP_BTNS.map(b => `<button class="btn btn-outline" onclick="batchRun('${b.step}')">${b.icon} 批量 ${b.label}</button>`).join('')}
    </div></div>
    <div id="wb-shots-grid" class="wb-shots-grid"></div>
    <div id="wb-batch-status" class="wb-batch-status" style="display:none"></div>`;
  renderShotsGrid();
}

function renderShotsGrid() {
  const grid = document.getElementById('wb-shots-grid');
  if (!grid) return;
  grid.innerHTML = shots.map((s, i) => {
    const sid = _shotId(s, i);
    return `<div class="wb-shot-card" id="shot-${sid}">
      <div class="wb-shot-head"><span class="wb-shot-num">${sid}</span><span class="wb-shot-char">${s.characters || ''}</span><span class="wb-shot-scene">${s.scene || ''}</span></div>
      <div class="wb-shot-body"><div class="wb-shot-text"><div class="wb-shot-action">${(s.action || '').substring(0, 20) || '...'}</div>
        <div class="wb-shot-dialogue">"${(s.dialogue || '').substring(0, 20) || '...'}"</div></div>
        <div class="wb-shot-resources" id="res-${sid}"></div></div>
      <div class="wb-shot-actions">${_actionBtns(i)}</div></div>`;
  }).join('');
  shots.forEach((_, i) => loadResources(i));
}

async function loadResources(idx) {
  const sid = _shotId(shots[idx], idx), el = document.getElementById(`res-${sid}`);
  if (!el) return;
  try {
    const r = (await cachedFetch(`res/${ep}/${sid}`, () => api(`/shots/${ep}/${sid}/resources`))).resources || {};
    const chips = [
      r.audio && `<div class="res-chip res-audio" onclick="previewRes('${sid}','audio')">🎤</div>`,
      r.frame && `<div class="res-chip res-img" onclick="previewRes('${sid}','frame')"><img src="/api/files/${ep}/${sid}/frame.png" loading="lazy"></div>`,
      r.video && `<div class="res-chip res-video" onclick="previewRes('${sid}','video')">🎬</div>`,
      r.synced && `<div class="res-chip res-video" onclick="previewRes('${sid}','synced')">👄</div>`,
    ].filter(Boolean).join('');
    el.innerHTML = chips || '<span class="dim" style="font-size:0.7rem">暂无资源</span>';
  } catch {}
}

function previewRes(sid, type) {
  const o = document.createElement('div'); o.className = 'res-overlay'; o.onclick = () => o.remove();
  const src = type === 'audio' ? `/api/files/${ep}/${sid}/audio.wav`
    : type === 'frame' ? `/api/files/${ep}/${sid}/frame.png`
    : `/api/files/${ep}/${sid}/${type === 'synced' ? 'synced.mp4' : 'video.mp4'}`;
  const tag = type === 'audio' ? `audio controls src="${src}" style="width:400px"`
    : type === 'frame' ? `img src="${src}" style="max-width:90vw;max-height:80vh;border-radius:8px"`
    : `video controls src="${src}" style="max-width:90vw;max-height:80vh;border-radius:8px"`;
  o.innerHTML = `<div class="res-overlay-inner"><${tag}><div class="dim" style="margin-top:0.5rem">点击空白处关闭 · ESC</div></div>`;
  document.body.appendChild(o);
}

// ── 镜头编辑 ──

const CAMERAS = ['固定', '缓慢推近', '跟随平移', '手持晃动', '环绕', '俯视', '仰视'];
const SHOT_TYPES = ['特写', '近景', '中景', '过肩', '全身', '全景', '远景'];
const EMOTIONS = ['neutral', 'happy', 'sad', 'angry', 'worried', 'surprised', 'calm', 'determined'];

function _selectOpts(options, current) { return options.map(o => `<option ${current === o ? 'selected' : ''}>${o}</option>`).join(''); }

function editShot(idx) {
  activeShot = idx;
  const s = shots[idx], sid = _shotId(s, idx);
  _showOverlay('edit-overlay', `✏️ 编辑镜头 ${sid}`, `
    <div class="edit-field"><label>场景</label><input id="ed-scene" value="${esc(s.scene || '')}"></div>
    <div class="edit-field"><label>角色</label><input id="ed-chars" value="${esc(s.characters || '')}"></div>
    <div class="edit-field"><label>动作</label><textarea id="ed-action" rows="2">${esc(s.action || '')}</textarea></div>
    <div class="edit-field"><label>台词</label><textarea id="ed-dialogue" rows="2">${esc(s.dialogue || '')}</textarea></div>
    <div class="edit-field-row">
      <div class="edit-field"><label>运镜</label><select id="ed-camera">${_selectOpts(CAMERAS, s.camera)}</select></div>
      <div class="edit-field"><label>景别</label><select id="ed-shottype">${_selectOpts(SHOT_TYPES, s.shot_type)}</select></div>
      <div class="edit-field"><label>时长</label><input id="ed-dur" type="number" value="${s.duration || 4}" min="1" max="30"></div>
      <div class="edit-field"><label>情绪</label><select id="ed-emo">${_selectOpts(EMOTIONS, s.emotion)}</select></div>
    </div>`, `saveShot(${idx})`);
}

async function saveShot(idx) {
  const s = shots[idx];
  for (const [k, id] of [['scene', 'ed-scene'], ['characters', 'ed-chars'], ['action', 'ed-action'], ['dialogue', 'ed-dialogue'], ['camera', 'ed-camera'], ['shot_type', 'ed-shottype'], ['duration', 'ed-dur'], ['emotion', 'ed-emo']])
    s[k] = document.getElementById(id)?.value || (k === 'duration' ? 4 : k === 'emotion' ? 'neutral' : '');
  pushUndo(`编辑镜头 ${s.shot_id || idx + 1}`);
  try { await api(`/storyboard/${ep}`, { method: 'POST', body: { shots } }); invalidateCache(`storyboard/${ep}`); invalidateCache(`res/${ep}`); toast('✅ 已保存'); document.getElementById('edit-overlay')?.remove(); renderShotsGrid(); } catch (e) { toast(e.message, 'error'); }
}

async function deleteShot(idx) {
  const sid = _shotId(shots[idx], idx);
  if (!confirm(t('confirm.delete_shot', { id: sid }))) return;
  pushUndo(`删除镜头 ${sid}`); shots.splice(idx, 1);
  try { await api(`/storyboard/${ep}`, { method: 'POST', body: { shots } }); invalidateCache(`storyboard/${ep}`); toast('✅ 已删除'); renderShotsGrid(); } catch (e) { toast(e.message, 'error'); }
}

// ── 执行 ──

async function runOne(step, idx) {
  const sid = _shotId(shots[idx], idx);
  const actionsEl = document.getElementById(`shot-${sid}`)?.querySelector('.wb-shot-actions');
  if (actionsEl) actionsEl.innerHTML = `<span class="run-indicator">⏳ ${step}...</span>`;
  try {
    const { task_id } = await fetch(`${API}/steps/${step}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ episode: ep, shot_id: sid }) }).then(r => r.ok ? r.json() : Promise.reject(r));
    const result = await pollTask(task_id, info => { if (actionsEl) actionsEl.innerHTML = `<span class="run-indicator">⏳ ${info.message || step} (${info.progress || 0}%)</span>`; });
    if (result.status === 'success') toast(`✅ ${sid} ${step} 完成`);
    else if (result.status === 'timeout') toast(`⏰ ${sid} ${step}: 轮询超时`, 'error');
    else toast(`❌ ${sid} ${step}: ${result.error || '失败'}`, 'error');
  } catch (e) { toast(`❌ ${sid}: ${e.message || e}`, 'error'); }
  if (actionsEl) actionsEl.innerHTML = _actionBtns(idx);
  invalidateCache(`res/${ep}/${sid}`); loadResources(idx);
}

function _batchSummary(done, skip, fail, cancelled) {
  return `<div class="batch-done">${cancelled ? '⏹ 已取消' : '✅ 完成'} · ✅ ${done} · ⏭ ${skip} · ❌ ${fail}
    <button class="btn btn-sm btn-outline" style="margin-left:0.5rem" onclick="this.parentElement.parentElement.style.display='none'">关闭</button></div>`;
}

async function batchRun(step) {
  const names = { tts: 'TTS', first_frame: '首帧', video: '视频', lipsync: '口型同步' };
  if (!confirm(`批量执行 ${names[step]}？共 ${shots.length} 个镜头`)) return;
  batchCancelled = false;
  const statusEl = document.getElementById('wb-batch-status');
  statusEl.style.display = 'block';
  let done = 0, fail = 0, skip = 0;
  for (let i = 0; i < shots.length; i++) {
    if (batchCancelled) { statusEl.innerHTML = _batchSummary(done, skip, fail, true); toast(`批量已取消`); return; }
    const sid = _shotId(shots[i], i);
    statusEl.innerHTML = `<div class="batch-progress"><div class="batch-bar"><div class="batch-fill" style="width:${(i / shots.length) * 100}%"></div></div>
      <div class="batch-text">[${i + 1}/${shots.length}] ${sid} — ${names[step]}...</div>
      <button class="btn btn-sm btn-danger" onclick="batchCancelled=true" style="margin-top:0.3rem">⏹ 取消</button></div>`;
    try {
      const r = await fetch(`${API}/steps/${step}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ episode: ep, shot_id: sid }) });
      if (!r.ok) { fail++; continue; }
      const { task_id } = await r.json();
      const result = await pollTask(task_id);
      if (result.status === 'success') {
        const stepResult = result.result?.details?.[step] || result.result;
        stepResult?.status === 'skipped' ? skip++ : (done++, invalidateCache(`res/${ep}/${sid}`), loadResources(i));
      } else fail++;
    } catch { fail++; }
  }
  statusEl.innerHTML = _batchSummary(done, skip, fail, false);
  toast(`批量完成: ${done}成功 ${skip}跳过 ${fail}失败`);
}

// ══════════════════════════════════════════════════════════
// 角色管理
// ══════════════════════════════════════════════════════════

const CHAR_COLS = [
  { key: 'id', label: 'ID' }, { key: 'name', label: '姓名' }, { key: 'gender', label: '性别' },
  { key: 'appearance', label: '外观', render: c => (c.appearance || '').substring(0, 40) },
];

async function loadCharacters() {
  const el = document.getElementById('page-characters');
  try { const d = await cachedFetch('characters', () => api('/characters')); el.innerHTML = _crudPage('👤 角色', CHAR_COLS, d.characters || [], 'editChar', 'deleteChar', 'newChar'); } catch (e) { el.innerHTML = `<div class="card"><h2>❌</h2><p>${esc(e.message)}</p></div>`; }
}
function newChar() { _crudCreate('characters', { gender: '', appearance: '', outfits: {}, voice: {} }, loadCharacters); }
function deleteChar(id) { _crudDelete('characters', id, '角色', loadCharacters); }

async function editChar(id) {
  const c = ((await cachedFetch('characters', () => api('/characters'))).characters || []).find(x => x.id === id);
  if (!c) { toast('角色不存在', 'error'); return; }
  _showOverlay('edit-char-overlay', `✏️ 编辑角色 ${id}`, `
    <div class="edit-field"><label>姓名</label><input id="ec-name" value="${esc(c.name || '')}"></div>
    <div class="edit-field"><label>性别</label><select id="ec-gender"><option value="">-</option><option value="male" ${c.gender === 'male' ? 'selected' : ''}>男</option><option value="female" ${c.gender === 'female' ? 'selected' : ''}>女</option></select></div>
    <div class="edit-field"><label>外观</label><textarea id="ec-appearance" rows="3">${esc(c.appearance || '')}</textarea></div>`, `saveCharEdit('${id}')`);
}
function saveCharEdit(id) { _crudSave('characters', id, () => ({ name: val('ec-name'), gender: val('ec-gender'), appearance: val('ec-appearance') }), 'edit-char-overlay', loadCharacters); }

// ══════════════════════════════════════════════════════════
// 场景管理
// ══════════════════════════════════════════════════════════

const SCENE_COLS = [
  { key: 'id', label: 'ID' }, { key: 'name', label: '名称' },
  { key: 'description', label: '描述', render: s => (s.description || '').substring(0, 40) },
];

async function loadScenes() {
  const el = document.getElementById('page-scenes');
  try { const d = await cachedFetch('scenes', () => api('/scenes')); el.innerHTML = _crudPage('🏔️ 场景', SCENE_COLS, d.scenes || [], 'editScene', 'deleteScene', 'newScene'); } catch (e) { el.innerHTML = `<div class="card"><h2>❌</h2><p>${esc(e.message)}</p></div>`; }
}
function newScene() { _crudCreate('scenes', { description: '', lighting: '' }, loadScenes); }
function deleteScene(id) { _crudDelete('scenes', id, '场景', loadScenes); }

async function editScene(id) {
  const s = ((await cachedFetch('scenes', () => api('/scenes'))).scenes || []).find(x => x.id === id);
  if (!s) { toast('场景不存在', 'error'); return; }
  _showOverlay('edit-scene-overlay', `✏️ 编辑场景 ${id}`, `
    <div class="edit-field"><label>名称</label><input id="es-name" value="${esc(s.name || '')}"></div>
    <div class="edit-field"><label>描述</label><textarea id="es-desc" rows="3">${esc(s.description || '')}</textarea></div>
    <div class="edit-field"><label>光照</label><input id="es-lighting" value="${esc(s.lighting || '')}"></div>`, `saveSceneEdit('${id}')`);
}
function saveSceneEdit(id) { _crudSave('scenes', id, () => ({ name: val('es-name'), description: val('es-desc'), lighting: val('es-lighting') }), 'edit-scene-overlay', loadScenes); }

// ── DOM 取值快捷 ──
function val(id) { return document.getElementById(id)?.value || ''; }

// ══════════════════════════════════════════════════════════
// 分镜表
// ══════════════════════════════════════════════════════════

const SB_FIELDS = ['scene', 'characters', 'action', 'dialogue', 'camera', 'shot_type', 'duration'];

async function loadStoryboard() {
  const el = document.getElementById('page-storyboard');
  try {
    const d = await cachedFetch(`storyboard/${ep}`, () => api(`/storyboard/${ep}`));
    const ss = d.shots || [];
    const rows = ss.map((s, i) => `<tr>
      <td>${_shotId(s, i)}</td>
      ${SB_FIELDS.slice(0, 4).map(f => `<td><input class="sb-inline-input" value="${esc(s[f] || '')}" data-idx="${i}" data-field="${f}" onchange="updateShotField(this)"></td>`).join('')}
      <td><select class="sb-inline-input" data-idx="${i}" data-field="camera" onchange="updateShotField(this)">${_selectOpts(CAMERAS, s.camera)}</select></td>
      <td><select class="sb-inline-input" data-idx="${i}" data-field="shot_type" onchange="updateShotField(this)">${_selectOpts(SHOT_TYPES, s.shot_type)}</select></td>
      <td><input class="sb-inline-input" type="number" value="${s.duration || 4}" min="1" max="30" data-idx="${i}" data-field="duration" onchange="updateShotField(this)"></td>
      <td><button class="btn btn-xs btn-danger" onclick="deleteShotFromSB(${i})">🗑️</button></td></tr>`).join('');
    el.innerHTML = `<div class="card"><div style="display:flex;justify-content:space-between;margin-bottom:1rem"><h2>📝 分镜表</h2>
      <div><button class="btn btn-primary" onclick="navTo('pipeline')">🎬 工作台</button><button class="btn btn-success" style="margin-left:0.5rem" onclick="addShot()">+ 添加</button></div></div>
      <div style="overflow-x:auto"><table><thead><tr><th>镜号</th><th>场景</th><th>角色</th><th>动作</th><th>台词</th><th>运镜</th><th>景别</th><th>时长</th><th></th></tr></thead>
      <tbody>${rows || '<tr><td colspan="9" class="dim" style="text-align:center">暂无</td></tr>'}</tbody></table></div></div>`;
  } catch (e) { el.innerHTML = `<div class="card"><h2>❌</h2><p>${esc(e.message)}</p></div>`; }
}

let _sbDirty = false;
const _debouncedSaveSB = debounce(async () => {
  if (!_sbDirty) return;
  try {
    const current = (await api(`/storyboard/${ep}`)).shots || [];
    document.querySelectorAll('.sb-inline-input').forEach(inp => { const i = parseInt(inp.dataset.idx); if (current[i]) current[i][inp.dataset.field] = inp.value; });
    await api(`/storyboard/${ep}`, { method: 'POST', body: { shots: current } }); invalidateCache(`storyboard/${ep}`); _sbDirty = false; toast('✅ 已保存');
  } catch (e) { toast(e.message, 'error'); }
}, 1000);
function updateShotField() { _sbDirty = true; _debouncedSaveSB(); }

async function deleteShotFromSB(idx) {
  const current = (await api(`/storyboard/${ep}`)).shots || [];
  if (!confirm(t('confirm.delete_shot', { id: current[idx]?.shot_id || idx + 1 }))) return;
  pushUndo(`删除镜头 ${current[idx]?.shot_id || idx + 1}`); current.splice(idx, 1);
  try { await api(`/storyboard/${ep}`, { method: 'POST', body: { shots: current } }); invalidateCache(`storyboard/${ep}`); toast('✅ 已删除'); loadStoryboard(); } catch (e) { toast(e.message, 'error'); }
}

async function addShot() {
  const existing = (await api(`/storyboard/${ep}`)).shots || [];
  const maxNum = Math.max(0, ...existing.map(s => parseInt(s.shot_id, 10)).filter(n => !isNaN(n)));
  const newId = String(maxNum + 1).padStart(3, '0');
  pushUndo(`添加镜头 ${newId}`);
  try { await api(`/storyboard/${ep}`, { method: 'POST', body: { shots: [...existing, { episode: ep, shot_id: newId, scene: '', characters: '', action: '', dialogue: '......', camera: '固定', shot_type: '中景', duration: 4, emotion: 'neutral', outfit: '', action_en: '', dialogue_en: '' }] } }); invalidateCache(`storyboard/${ep}`); toast('已添加'); loadStoryboard(); } catch (e) { toast(e.message, 'error'); }
}

// ══════════════════════════════════════════════════════════
// 项目管理
// ══════════════════════════════════════════════════════════

async function loadProjects() {
  const el = document.getElementById('page-projects');
  try {
    const d = await api('/projects');
    const rows = (d.projects || []).map(p => `<tr><td>${p.active ? '→' : ''}</td><td>${p.name}</td><td class="dim" style="font-size:0.75rem">${p.path}</td><td>${p.active ? '<span class="badge badge-green">当前</span>' : `<button class="btn btn-sm btn-primary" onclick="switchProj('${p.name}')">切换</button>`}</td></tr>`).join('');
    el.innerHTML = `<div class="card"><div style="display:flex;justify-content:space-between;margin-bottom:1rem"><h2>📂 项目</h2><button class="btn btn-success" onclick="newProj()">+ 新建</button></div>
      <table><thead><tr><th></th><th>名称</th><th>路径</th><th>状态</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  } catch (e) { el.innerHTML = `<div class="card"><h2>❌</h2><p>${esc(e.message)}</p></div>`; }
}
function newProj() { const n = prompt('名称:'); if (!n) return; api('/projects/new', { method: 'POST', body: { name: n } }).then(() => { toast('已创建'); loadProjects(); }).catch(e => toast(e.message, 'error')); }
function switchProj(n) { api('/projects/switch', { method: 'POST', body: { name: n } }).then(() => { toast(`已切换: ${n}`); loadProjects(); }).catch(e => toast(e.message, 'error')); }

// ══════════════════════════════════════════════════════════
// 系统设置
// ══════════════════════════════════════════════════════════

function _backendSection(label, icon, idPrefix, backends, backend, url, available, reason) {
  return `<div class="config-section"><h3>${icon} ${label}</h3>
    <div class="form-row"><label>后端</label><select id="cfg-${idPrefix}" onchange="_updateUrl('${idPrefix}')">${backends.map(b => `<option value="${b}" ${backend === b ? 'selected' : ''}>${b}</option>`).join('')}</select></div>
    <div class="form-row"><label>地址</label><input id="cfg-${idPrefix}-url" value="${esc(url)}"></div>
    <div class="tool-status-inline"><span class="status-dot ${available ? 'ok' : 'err'}"></span>${available ? '可用' : reason || '不可用'}</div></div>`;
}

function _updateUrl(prefix) {
  const key = val(`cfg-${prefix}`).replace(/-/g, '_');
  const cfg = _cache.get('config')?.data || {};
  const inp = document.getElementById(`cfg-${prefix}-url`);
  if (inp) inp.value = cfg.models?.[key]?.api_url || '';
}

function _resolveBackendUrl(cfg, prefix) {
  const backend = cfg.models?.[`${prefix}_backend`] || '';
  return { backend, url: cfg.models?.[backend.replace(/-/g, '_')]?.api_url || '' };
}

async function loadSettings() {
  const el = document.getElementById('page-settings');
  try {
    const [cfg, env, td] = await Promise.all([api('/config'), api('/system/env'), api('/tools')]);
    _cache.set('config', { data: cfg, ts: Date.now() });
    const t = td.tools || {}, lang = localStorage.getItem('drama_lang') || 'zh';
    const tts = _resolveBackendUrl(cfg, 'tts'), ls = _resolveBackendUrl(cfg, 'lip_sync');
    el.innerHTML = `
      <div class="card"><h2>🌐 语言 / Language</h2><div class="form-row"><label>界面语言</label>
        <select id="cfg-lang" onchange="setLang(this.value);loadSettings()"><option value="zh" ${lang === 'zh' ? 'selected' : ''}>中文</option><option value="en" ${lang === 'en' ? 'selected' : ''}>English</option></select></div></div>
      <div class="card"><h2>💻 环境</h2><div class="info-grid"><div><span class="dim">OS:</span> ${env.os}</div><div><span class="dim">Python:</span> ${env.python}</div><div><span class="dim">GPU:</span> ${env.gpu.available ? env.gpu.name + ' (' + env.gpu.vram_mb + 'MB)' : '不可用'}</div></div></div>
      <div class="card"><h2>🔧 配置</h2>
        ${_backendSection('TTS', '🎤', 'tts', ['mimo-voicedesign', 'mimo-voiceclone', 'gpt-sovits', 'cosyvoice', 'fish-speech'], tts.backend, tts.url, t.tts?.available, t.tts?.reason)}
        ${_backendSection('LipSync', '👄', 'lipsync', ['musetalk', 'sadtalker', 'wav2lip'], ls.backend, ls.url, t.lipsync?.available, t.lipsync?.reason)}
        <div class="config-section"><h3>🎨 ComfyUI</h3>
          <div class="form-row"><label>地址</label><input id="cfg-comfyui" value="${esc(cfg.comfyui?.url || '')}"></div>
          <div class="tool-status-inline"><span class="status-dot ${t.comfyui?.available ? 'ok' : 'err'}"></span>${t.comfyui?.available ? '可用' : t.comfyui?.reason || '不可用'}</div></div>
        <button class="btn btn-primary" style="margin-top:1rem" onclick="saveCfg()">💾 保存</button></div>`;
  } catch (e) { el.innerHTML = `<div class="card"><h2>❌</h2><p>${esc(e.message)}</p></div>`; }
}

async function saveCfg() {
  try {
    const cfg = await api('/config'); cfg.models = cfg.models || {};
    for (const [prefix, idPrefix] of [['tts', 'tts'], ['lip_sync', 'lipsync']]) {
      const backend = val(`cfg-${idPrefix}`); cfg.models[`${prefix}_backend`] = backend;
      const key = backend.replace(/-/g, '_'); cfg.models[key] = cfg.models[key] || {}; cfg.models[key].api_url = val(`cfg-${idPrefix}-url`);
    }
    cfg.comfyui = cfg.comfyui || {}; cfg.comfyui.url = val('cfg-comfyui');
    await api('/config', { method: 'POST', body: cfg }); toast('✅ 已保存');
  } catch (e) { toast(e.message, 'error'); }
}

loadDashboard();

// AI 短剧工作台 v2
const API = '/api';

// ── 基础设施 ──

const _cache = new Map();
const CACHE_TTL = 30000;
const MAX_UNDO = 50;
const MAX_POLL = 300;

let ep = 1, shots = [], activeShot = 0, batchCancelled = false;
const _undoStack = [], _redoStack = [];

// ── 集数选择器 ──
async function loadEpisodeSelector() {
  try {
    const d = await api('/episodes');
    const eps = d.episodes || [1];
    // 确保当前集在列表中
    if (!eps.includes(ep)) eps.push(ep);
    return eps.sort((a, b) => a - b);
  } catch { return [ep]; }
}

function _episodeSelectHtml(episodes, onChangeFn) {
  const opts = episodes.map(e => `<option value="${e}" ${e === ep ? 'selected' : ''}>${e}</option>`).join('');
  return `<select class="btn btn-outline" style="padding:.3rem .6rem;font-size:.82rem" onchange="${onChangeFn}(this.value)">${opts}</select><button class="btn btn-xs btn-outline" onclick="addEpisode()" title="${t('btn.add')}">+</button>`;
}

function switchEpisode(val) {
  ep = parseInt(val) || 1;
  invalidateCache(`storyboard/${ep}`);
  const p = document.querySelector('.page.active');
  if (p?.id === 'page-storyboard') loadStoryboard();
  else if (p?.id === 'page-pipeline') loadPipeline();
}

function addEpisode() {
  const input = prompt('Episode #:', '');
  if (!input) return;
  const newEp = parseInt(input);
  if (!newEp || newEp < 1) { toast('Invalid episode number', 'error'); return; }
  ep = newEp;
  invalidateCache('episodes');
  invalidateCache(`storyboard/${ep}`);
  const p = document.querySelector('.page.active');
  if (p?.id === 'page-storyboard') loadStoryboard();
  else if (p?.id === 'page-pipeline') loadPipeline();
  toast(`Episode ${ep}`);
}

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
  let delay = 500;
  for (let i = 0; i < MAX_POLL; i++) {
    const info = await api(`/tasks/${taskId}`);
    if (onProgress) onProgress(info);
    if (['success', 'failed', 'cancelled'].includes(info.status)) return info;
    await new Promise(r => setTimeout(r, delay));
    delay = Math.min(delay * 1.5, 5000); // 指数退避，上限5秒
  }
  return { status: 'timeout', error: t('toast.timeout') };
}

// ── 撤销/重做 ──

function _applyHistory(from, to, label) {
  if (!from.length) { toast(t('undo.no_action', { label }), 'error'); return; }
  const entry = from.pop();
  to.push({ shots: JSON.parse(JSON.stringify(shots)), desc: entry.desc });
  shots = entry.shots;
  invalidateCache(`storyboard/${ep}`);
  api(`/storyboard/${ep}`, { method: 'POST', body: { shots } }).then(() => {
    toast(`${label === t('undo.undo') ? '↩' : '↪'} ${label}: ${entry.desc}`);
    const p = document.querySelector('.page.active');
    p?.id === 'page-storyboard' ? loadStoryboard() : renderShotsGrid();
  }).catch(e => toast(e.message, 'error'));
}
function pushUndo(desc) { _undoStack.push({ shots: JSON.parse(JSON.stringify(shots)), desc }); if (_undoStack.length > MAX_UNDO) _undoStack.shift(); _redoStack.length = 0; }
function undo() { _applyHistory(_undoStack, _redoStack, t('undo.undo')); }
function redo() { _applyHistory(_redoStack, _undoStack, t('undo.redo')); }

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
  const ths = cols.map(c => `<th>${c.label}</th>`).join('') + `<th>${t('common.operations')}</th>`;
  const rows = items.length
    ? items.map(it => {
      const tds = cols.map(c => `<td>${c.render ? c.render(it) : esc(it[c.key] || '')}</td>`).join('');
      return `<tr>${tds}<td><button class="btn btn-xs" onclick="${editFn}('${it.id}')">✏️</button>
        <button class="btn btn-xs btn-danger" onclick="${delFn}('${it.id}')">🗑️</button></td></tr>`;
    }).join('')
    : `<tr><td colspan="${cols.length + 1}" class="dim" style="text-align:center">${t('common.none')}</td></tr>`;
  return `<table><thead><tr>${ths}</tr></thead><tbody>${rows}</tbody></table>`;
}

function _crudPage(title, cols, items, editFn, delFn, newFn, emptyHint) {
  const table = _crudTable(cols, items, editFn, delFn);
  const hint = !items.length && emptyHint ? `<p class="dim" style="margin-top:0.5rem;font-size:0.85rem">${emptyHint}</p>` : '';
  return `<div class="card"><div style="display:flex;justify-content:space-between;margin-bottom:1rem">
    <h2>${title}</h2><button class="btn btn-success" onclick="${newFn}()">+ ${t('btn.add').replace('+ ', '')}</button></div>${table}${hint}</div>`;
}

async function _crudDelete(endpoint, id, label, reload) {
  if (!confirm(`${label} ${id}？`)) return;
  try { await api(`/${endpoint}/${id}`, { method: 'DELETE' }); invalidateCache(endpoint); toast(t('toast.deleted')); reload(); } catch (e) { toast(e.message, 'error'); }
}
async function _crudSave(endpoint, id, fieldsFn, overlayId, reload) {
  try { await api(`/${endpoint}`, { method: 'POST', body: { id, ...fieldsFn() } }); invalidateCache(endpoint); document.getElementById(overlayId)?.remove(); toast(t('toast.saved')); reload(); } catch (e) { toast(e.message, 'error'); }
}

function _showOverlay(id, title, bodyHtml, saveFn) {
  const o = document.createElement('div'); o.className = 'edit-overlay'; o.id = id;
  o.innerHTML = `<div class="edit-panel"><div class="edit-header"><h3>${title}</h3>
    <button class="btn btn-sm btn-outline" onclick="document.getElementById('${id}')?.remove()">✕</button></div>
    <div class="edit-body">${bodyHtml}</div><div class="edit-footer">
    <button class="btn btn-primary" onclick="${saveFn}">💾 ${t('btn.save').replace('💾 ', '')}</button>
    <button class="btn btn-outline" onclick="document.getElementById('${id}')?.remove()">${t('btn.cancel')}</button></div></div>`;
  document.body.appendChild(o);
  o.querySelector('input,textarea')?.focus();
}

// ══════════════════════════════════════════════════════════
// 仪表盘
// ══════════════════════════════════════════════════════════

const TOOL_META = { redis:{icon:'🔴',label:'Redis'}, celery:{icon:'🔧',label:'Celery'}, ffmpeg:{icon:'🎞️',label:'FFmpeg'}, tts:{icon:'🎤',label:'TTS'}, comfyui:{icon:'🎨',label:'ComfyUI'}, lipsync:{icon:'👄',label:'LipSync'}, llm:{icon:'🧠',label:'LLM'}, music:{icon:'🎵',label:'Music'} };

async function loadDashboard() {
  const el = document.getElementById('page-dashboard');
  try {
    const s = await cachedFetch('system/status', () => api('/system/status'), 10000);
    const groups = [
      { label: t('dash.infra'), keys: ['redis', 'celery', 'ffmpeg'] },
      { label: t('dash.ai_tools'), keys: ['tts', 'music'] },
      { label: t('dash.gpu_tools'), keys: ['comfyui', 'lipsync', 'llm'] },
    ];
    let html = '';
    for (const g of groups) {
      html += `<div class="section-label">${g.label}</div><div class="tool-grid">`;
      for (const k of g.keys) {
        const info = s.tools[k] || {}, meta = TOOL_META[k] || {};
        html += `<div class="tool-card ${info.available ? 'tool-ok' : 'tool-off'}"><span>${meta.icon} ${meta.label}</span>
          <span class="status-dot ${info.available ? 'ok' : 'err'}"></span>
          <span class="dim" style="font-size:0.75rem">${info.available ? t('dash.available') : info.reason || t('dash.unavailable')}</span></div>`;
      }
      html += '</div>';
    }
    el.innerHTML = `<div class="card"><h2>${t('dash.title')}</h2>${html}</div>
      <div class="card"><h2>${t('dash.start')}</h2><p class="dim" style="margin-bottom:0.5rem">${t('dash.start_hint')}</p>
      <button class="btn btn-primary" onclick="navTo('pipeline')">${t('dash.enter_wb')}</button></div>`;
  } catch (e) { el.innerHTML = `<div class="card"><h2>${t('dash.conn_fail')}</h2><p>${esc(e.message)}</p></div>`; }
}

// ══════════════════════════════════════════════════════════
// 生产工作台
// ══════════════════════════════════════════════════════════

const STEP_BTNS = [
  { step: 'tts', icon: '🎤', label: 'TTS' },
  { step: 'first-frame', icon: '🎨', label: t('step.first_frame') },
  { step: 'video', icon: '🎬', label: t('step.video') },
  { step: 'lipsync', icon: '👄', label: t('step.lipsync') },
];

function _shotId(s, i) { return s.shot_id || String(i + 1).padStart(3, '0'); }
function _actionBtns(idx) {
  return `<button class="btn btn-xs" onclick="editShot(${idx})" title="${t('btn.edit')}">✏️</button>` +
    STEP_BTNS.map(b => `<button class="btn btn-xs" onclick="runOne('${b.step}',${idx})" title="${b.label}">${b.icon}</button>`).join('') +
    `<button class="btn btn-xs btn-danger" onclick="deleteShot(${idx})" title="${t('btn.delete')}">🗑️</button>`;
}

async function loadPipeline() {
  const el = document.getElementById('page-pipeline');
  el.innerHTML = `<div class="card"><h2>${t('common.loading')}</h2></div>`;
  try {
    const episodes = await loadEpisodeSelector();
    const d = await cachedFetch(`storyboard/${ep}`, () => api(`/storyboard/${ep}`));
    shots = d.shots || [];
    if (!shots.length) { el.innerHTML = `<div class="card"><h2>${t('wb.no_storyboard')}</h2><p class="dim">${t('wb.add_shots_first')}</p><button class="btn btn-primary" style="margin-top:0.5rem" onclick="navTo('storyboard')">${t('wb.go_edit_btn')}</button></div>`; return; }
    renderWB(episodes);
  } catch (e) { el.innerHTML = `<div class="card"><h2>${t('common.error')}</h2><p>${esc(e.message)}</p></div>`; }
}

function renderWB(episodes) {
  const el = document.getElementById('page-pipeline');
  const epSelector = _episodeSelectHtml(episodes || [ep], 'switchEpisode');
  el.innerHTML = `<div class="wb-top-bar"><div style="display:flex;align-items:center;gap:0.5rem"><h2>🎬 ${t('nav.pipeline').replace('🎬 ', '')}</h2>${epSelector}<span class="dim" style="font-size:.85rem">${shots.length} ${t('wb.shots_count')}</span></div>
    <div class="wb-batch-btns">
      <button class="btn btn-outline" onclick="undo()" title="Ctrl+Z">↩ ${t('undo.undo')}</button>
      <button class="btn btn-outline" onclick="redo()" title="Ctrl+Shift+Z">↪ ${t('undo.redo')}</button>
      ${STEP_BTNS.map(b => `<button class="btn btn-outline" onclick="batchRun('${b.step}')">${b.icon} ${t('wb.batch_label')} ${b.label}</button>`).join('')}
      <span class="dim" style="margin:0 0.3rem">|</span>
      <button class="btn btn-outline" onclick="runPortraits()">📸 ${t('wb.gen_portraits').replace('📸 ', '')}</button>
      <button class="btn btn-outline" onclick="runPost()">🎞️ ${t('wb.post_process').replace('🎞️ ', '')}</button>
      <button class="btn btn-outline" onclick="runMusic()">🎵 ${t('wb.gen_music').replace('🎵 ', '')}</button>
      <button class="btn btn-outline" onclick="runSubtitle()">📝 ${t('wb.gen_subtitle').replace('📝 ', '')}</button>
      <button class="btn btn-primary" onclick="runAll()">🚀 ${t('wb.run_all').replace('🚀 ', '')}</button>
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
    el.innerHTML = chips || `<span class="dim" style="font-size:0.7rem">${t('wb.no_resource')}</span>`;
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
  o.innerHTML = `<div class="res-overlay-inner"><${tag}><div class="dim" style="margin-top:0.5rem">${t('wb.esc_hint')}</div></div>`;
  document.body.appendChild(o);
}

// ── 镜头编辑 ──

const CAMERAS = [t('camera.fixed'), t('camera.push_in'), t('camera.pan'), t('camera.handheld'), t('camera.orbit'), t('camera.top'), t('camera.bottom')];
const SHOT_TYPES = [t('shot.closeup'), t('shot.medium_close'), t('shot.medium'), t('shot.over_shoulder'), t('shot.full'), t('shot.wide'), t('shot.extreme_wide')];
const EMOTIONS = ['neutral', 'happy', 'sad', 'angry', 'worried', 'surprised', 'calm', 'determined'];

function _selectOpts(options, current) { return options.map(o => `<option ${current === o ? 'selected' : ''}>${o}</option>`).join(''); }

function editShot(idx) {
  activeShot = idx;
  const s = shots[idx], sid = _shotId(s, idx);
  _showOverlay('edit-overlay', `${t('edit.shot_title')} ${sid}`, `
    <div class="edit-field"><label>${t('edit.scene')}</label><input id="ed-scene" value="${esc(s.scene || '')}"></div>
    <div class="edit-field"><label>${t('edit.characters')}</label><input id="ed-chars" value="${esc(s.characters || '')}"></div>
    <div class="edit-field"><label>${t('edit.action')}</label><textarea id="ed-action" rows="2">${esc(s.action || '')}</textarea></div>
    <div class="edit-field"><label>${t('sb.action_en')}</label><textarea id="ed-action-en" rows="2">${esc(s.action_en || '')}</textarea></div>
    <div class="edit-field"><label>${t('edit.dialogue')}</label><textarea id="ed-dialogue" rows="2">${esc(s.dialogue || '')}</textarea></div>
    <div class="edit-field"><label>${t('sb.dialogue_en')}</label><textarea id="ed-dialogue-en" rows="2">${esc(s.dialogue_en || '')}</textarea></div>
    <div class="edit-field-row">
      <div class="edit-field"><label>${t('edit.camera')}</label><select id="ed-camera">${_selectOpts(CAMERAS, s.camera)}</select></div>
      <div class="edit-field"><label>${t('edit.shot_type')}</label><select id="ed-shottype">${_selectOpts(SHOT_TYPES, s.shot_type)}</select></div>
      <div class="edit-field"><label>${t('edit.duration')}</label><input id="ed-dur" type="number" value="${s.duration || 4}" min="1" max="30"></div>
      <div class="edit-field"><label>${t('edit.emotion')}</label><select id="ed-emo">${_selectOpts(EMOTIONS, s.emotion)}</select></div>
    </div>`, `saveShot(${idx})`);
}

async function saveShot(idx) {
  const s = shots[idx];
  for (const [k, id] of [['scene', 'ed-scene'], ['characters', 'ed-chars'], ['action', 'ed-action'], ['action_en', 'ed-action-en'], ['dialogue', 'ed-dialogue'], ['dialogue_en', 'ed-dialogue-en'], ['camera', 'ed-camera'], ['shot_type', 'ed-shottype'], ['duration', 'ed-dur'], ['emotion', 'ed-emo']])
    s[k] = document.getElementById(id)?.value || (k === 'duration' ? 4 : k === 'emotion' ? 'neutral' : '');
  pushUndo(`编辑镜头 ${s.shot_id || idx + 1}`);
  try { await api(`/storyboard/${ep}`, { method: 'POST', body: { shots } }); invalidateCache(`storyboard/${ep}`); invalidateCache(`res/${ep}`); toast(t('toast.saved')); document.getElementById('edit-overlay')?.remove(); renderShotsGrid(); } catch (e) { toast(e.message, 'error'); }
}

async function deleteShot(idx) {
  const sid = _shotId(shots[idx], idx);
  if (!confirm(t('confirm.delete_shot', { id: sid }))) return;
  pushUndo(`删除镜头 ${sid}`); shots.splice(idx, 1);
  try { await api(`/storyboard/${ep}`, { method: 'POST', body: { shots } }); invalidateCache(`storyboard/${ep}`); toast(t('toast.deleted')); renderShotsGrid(); } catch (e) { toast(e.message, 'error'); }
}

// ── 执行 ──

async function runOne(step, idx) {
  const sid = _shotId(shots[idx], idx);
  const actionsEl = document.getElementById(`shot-${sid}`)?.querySelector('.wb-shot-actions');
  if (actionsEl) actionsEl.innerHTML = `<span class="run-indicator">⏳ ${step}...</span>`;
  try {
    const { task_id } = await api(`/steps/${step}`, { method: 'POST', body: { episode: ep, shot_id: sid } });
    const result = await pollTask(task_id, info => { if (actionsEl) actionsEl.innerHTML = `<span class="run-indicator">⏳ ${info.message || step} (${info.progress || 0}%)</span>`; });
    if (result.status === 'success') toast(`✅ ${sid} ${step} ${t('wb.shot_done')}`);
    else if (result.status === 'timeout') toast(`⏰ ${sid} ${step}: ${t('toast.timeout')}`, 'error');
    else toast(`❌ ${sid} ${step}: ${result.error || t('wb.shot_fail')}`, 'error');
  } catch (e) { toast(`❌ ${sid}: ${e.message}`, 'error'); }
  if (actionsEl) actionsEl.innerHTML = _actionBtns(idx);
  invalidateCache(`res/${ep}/${sid}`); loadResources(idx);
}

function _batchSummary(done, skip, fail, cancelled) {
  return `<div class="batch-done">${cancelled ? t('wb.batch_cancelled') : t('wb.batch_done')} · ${t('wb.batch_ok')} ${done} · ${t('wb.batch_skip')} ${skip} · ${t('wb.batch_fail')} ${fail}
    <button class="btn btn-sm btn-outline" style="margin-left:0.5rem" onclick="this.parentElement.parentElement.style.display='none'">${t('batch.close_btn')}</button></div>`;
}

async function batchRun(step) {
  const names = { tts: t('step.tts'), 'first-frame': t('step.first_frame'), video: t('step.video'), lipsync: t('step.lipsync') };
  if (!confirm(t('batch.confirm', { step: names[step], n: shots.length }))) return;
  batchCancelled = false;
  const statusEl = document.getElementById('wb-batch-status');
  statusEl.style.display = 'block';
  const concurrency = parseInt(localStorage.getItem('drama_concurrency') || '1');
  let done = 0, fail = 0, skip = 0, idx = 0;

  async function processShot(i) {
    if (batchCancelled) return;
    const sid = _shotId(shots[i], i);
    try {
      const { task_id } = await api(`/steps/${step}`, { method: 'POST', body: { episode: ep, shot_id: sid } });
      const result = await pollTask(task_id);
      if (result.status === 'success') {
        const stepResult = result.result?.details?.[step] || result.result;
        stepResult?.status === 'skipped' ? skip++ : (done++, invalidateCache(`res/${ep}/${sid}`), loadResources(i));
      } else fail++;
    } catch { fail++; }
  }

  if (concurrency <= 1) {
    // 串行
    for (let i = 0; i < shots.length; i++) {
      if (batchCancelled) break;
      const sid = _shotId(shots[i], i);
      statusEl.innerHTML = `<div class="batch-progress"><div class="batch-bar"><div class="batch-fill" style="width:${(i / shots.length) * 100}%"></div></div>
        <div class="batch-text">[${i + 1}/${shots.length}] ${sid} — ${t('batch.progress', { step: names[step] })}</div>
        <button class="btn btn-sm btn-danger" onclick="batchCancelled=true" style="margin-top:0.3rem">${t('batch.cancel_btn')}</button></div>`;
      await processShot(i);
    }
  } else {
    // 并发
    const pool = new Set();
    for (let i = 0; i < shots.length; i++) {
      if (batchCancelled) break;
      const sid = _shotId(shots[i], i);
      statusEl.innerHTML = `<div class="batch-progress"><div class="batch-bar"><div class="batch-fill" style="width:${(i / shots.length) * 100}%"></div></div>
        <div class="batch-text">[${i + 1}/${shots.length}] ${sid} — ${names[step]} (${t('batch.concurrent')}: ${concurrency})</div>
        <button class="btn btn-sm btn-danger" onclick="batchCancelled=true" style="margin-top:0.3rem">${t('batch.cancel_btn')}</button></div>`;
      const p = processShot(i).then(() => pool.delete(p));
      pool.add(p);
      if (pool.size >= concurrency) await Promise.race(pool);
    }
    await Promise.all(pool);
  }

  if (batchCancelled) { statusEl.innerHTML = _batchSummary(done, skip, fail, true); toast(t('toast.cancelled')); return; }
  statusEl.innerHTML = _batchSummary(done, skip, fail, false);
  toast(t('batch.complete', { done, skip, fail }));
}

// ── 管线工具 ──

async function runPortraits() {
  if (!confirm(t('wb.gen_portraits') + '?')) return;
  try {
    const { task_id } = await api('/tools/portraits', { method: 'POST' });
    toast('⏳ ' + t('wb.gen_portraits'));
    const result = await pollTask(task_id);
    if (result.status === 'success') toast('✅ ' + t('wb.gen_portraits'));
    else toast('❌ ' + (result.error || t('wb.shot_fail')), 'error');
  } catch (e) { toast('❌ ' + e.message, 'error'); }
}

async function runPost() {
  if (!confirm(t('wb.post_process') + '?')) return;
  try {
    const { task_id } = await api('/tools/post', { method: 'POST', body: { episode: ep } });
    toast('⏳ ' + t('wb.post_process'));
    const result = await pollTask(task_id);
    if (result.status === 'success') toast('✅ ' + t('wb.post_process'));
    else toast('❌ ' + (result.error || t('wb.shot_fail')), 'error');
  } catch (e) { toast('❌ ' + e.message, 'error'); }
}

async function runAll() {
  if (!confirm(t('wb.run_all') + '?')) return;
  const statusEl = document.getElementById('wb-batch-status');
  statusEl.style.display = 'block';
  const stages = ['preview', 'produce', 'post'];
  for (const cmd of stages) {
    statusEl.innerHTML = `<div class="batch-progress"><div class="batch-text">⏳ ${cmd}...</div></div>`;
    try {
      const { task_id } = await api('/pipeline/run', { method: 'POST', body: { episode: ep, command: cmd } });
      const result = await pollTask(task_id);
      if (result.status !== 'success') { statusEl.innerHTML = `<div class="batch-done">❌ ${cmd}: ${result.error || t('wb.shot_fail')}</div>`; return; }
    } catch (e) { statusEl.innerHTML = `<div class="batch-done">❌ ${cmd}: ${e.message}</div>`; return; }
  }
  statusEl.innerHTML = `<div class="batch-done">✅ ${t('wb.run_all')}</div>`;
  toast('✅ ' + t('wb.run_all'));
}

async function runMusic() {
  const duration = prompt(t('wb.music_duration') + ':', '60');
  if (!duration) return;
  const mood = prompt(t('wb.music_mood') + ':', 'neutral');
  try {
    const { task_id } = await api('/tools/music', { method: 'POST', body: { duration: parseFloat(duration), mood: mood || 'neutral' } });
    toast('⏳ ' + t('wb.gen_music'));
    const result = await pollTask(task_id);
    if (result.status === 'success') toast('✅ ' + t('wb.gen_music'));
    else toast('❌ ' + (result.error || t('wb.shot_fail')), 'error');
  } catch (e) { toast('❌ ' + e.message, 'error'); }
}

async function runSubtitle() {
  if (!confirm(t('wb.gen_subtitle') + '?')) return;
  try {
    const { task_id } = await api('/tools/subtitle', { method: 'POST', body: { episode: ep } });
    toast('⏳ ' + t('wb.gen_subtitle'));
    const result = await pollTask(task_id);
    if (result.status === 'success') toast('✅ ' + t('wb.gen_subtitle'));
    else toast('❌ ' + (result.error || t('wb.shot_fail')), 'error');
  } catch (e) { toast('❌ ' + e.message, 'error'); }
}

// ══════════════════════════════════════════════════════════
// 角色管理
// ══════════════════════════════════════════════════════════

const CHAR_COLS = [
  { key: 'id', label: 'ID' }, { key: 'name', label: t('char.name') }, { key: 'gender', label: t('char.gender') },
  { key: 'appearance', label: t('char.appearance'), render: c => (c.appearance || '').substring(0, 40) },
];

async function loadCharacters() {
  const el = document.getElementById('page-characters');
  try { const d = await cachedFetch('characters', () => api('/characters')); el.innerHTML = _crudPage(t('char.title'), CHAR_COLS, d.characters || [], 'editChar', 'deleteChar', 'newChar', t('char.empty_hint')); } catch (e) { el.innerHTML = `<div class="card"><h2>${t('common.error')}</h2><p>${esc(e.message)}</p></div>`; }
}
function newChar() {
  _showOverlay('new-char-overlay', `+ ${t('char.title').replace(/👤\s?/, '')}`, `
    <div class="edit-field"><label>ID</label><input id="nc-id" placeholder="a-z, 0-9, _-"></div>
    <div class="edit-field"><label>${t('char.name')}</label><input id="nc-name"></div>
    <div class="edit-field"><label>${t('char.gender')}</label><select id="nc-gender"><option value="">-</option><option value="male">${t('char.gender.male')}</option><option value="female">${t('char.gender.female')}</option></select></div>
    <div class="edit-field"><label>${t('char.appearance')}</label><textarea id="nc-appearance" rows="3"></textarea></div>
    <div class="edit-field"><label>${t('char.voice_key')}</label><input id="nc-voice" placeholder="e.g. male-1"></div>
    <div class="edit-field"><label>${t('char.outfit_desc')}</label><textarea id="nc-outfits" rows="2"></textarea></div>`, `saveNewChar()`);
}
async function saveNewChar() {
  const id = val('nc-id');
  if (!id || !/^[a-zA-Z0-9_-]+$/.test(id)) { toast('ID invalid', 'error'); return; }
  const voiceVal = val('nc-voice'), outfitVal = val('nc-outfits');
  try {
    await api('/characters', { method: 'POST', body: {
      id, name: val('nc-name'), gender: val('nc-gender'), appearance: val('nc-appearance'),
      voice: voiceVal ? { key: voiceVal } : null,
      outfits: outfitVal ? { default: outfitVal } : null,
    }});
    invalidateCache('characters'); document.getElementById('new-char-overlay')?.remove(); toast(t('toast.created')); loadCharacters();
  } catch (e) { toast(e.message, 'error'); }
}
function deleteChar(id) { _crudDelete('characters', id, t('char.title').replace(/👤\s?/, ''), loadCharacters); }

async function editChar(id) {
  const c = ((await cachedFetch('characters', () => api('/characters'))).characters || []).find(x => x.id === id);
  if (!c) { toast(t('char.not_found'), 'error'); return; }
  const voiceKey = c.voice?.key || '';
  const outfitDesc = c.outfits?.default || '';
  _showOverlay('edit-char-overlay', `${t('char.edit_title')} ${id}`, `
    <div class="edit-field"><label>${t('char.name')}</label><input id="ec-name" value="${esc(c.name || '')}"></div>
    <div class="edit-field"><label>${t('char.gender')}</label><select id="ec-gender"><option value="">-</option><option value="male" ${c.gender === 'male' ? 'selected' : ''}>${t('char.gender.male')}</option><option value="female" ${c.gender === 'female' ? 'selected' : ''}>${t('char.gender.female')}</option></select></div>
    <div class="edit-field"><label>${t('char.appearance')}</label><textarea id="ec-appearance" rows="3">${esc(c.appearance || '')}</textarea></div>
    <div class="edit-field"><label>${t('char.voice_key')}</label><input id="ec-voice" value="${esc(voiceKey)}" placeholder="e.g. male-1"></div>
    <div class="edit-field"><label>${t('char.outfit_desc')}</label><textarea id="ec-outfits" rows="2">${esc(outfitDesc)}</textarea></div>`, `saveCharEdit('${id}')`);
}
function saveCharEdit(id) {
  const voiceVal = val('ec-voice');
  const outfitVal = val('ec-outfits');
  _crudSave('characters', id, () => ({
    name: val('ec-name'), gender: val('ec-gender'), appearance: val('ec-appearance'),
    voice: voiceVal ? { key: voiceVal } : null,
    outfits: outfitVal ? { default: outfitVal } : null,
  }), 'edit-char-overlay', loadCharacters);
}

// ══════════════════════════════════════════════════════════
// 场景管理
// ══════════════════════════════════════════════════════════

const SCENE_COLS = [
  { key: 'id', label: 'ID' }, { key: 'name', label: t('scene.name') },
  { key: 'description', label: t('scene.desc'), render: s => (s.description || '').substring(0, 40) },
];

async function loadScenes() {
  const el = document.getElementById('page-scenes');
  try { const d = await cachedFetch('scenes', () => api('/scenes')); el.innerHTML = _crudPage(t('scene.title'), SCENE_COLS, d.scenes || [], 'editScene', 'deleteScene', 'newScene', t('scene.empty_hint')); } catch (e) { el.innerHTML = `<div class="card"><h2>${t('common.error')}</h2><p>${esc(e.message)}</p></div>`; }
}
function newScene() {
  _showOverlay('new-scene-overlay', `+ ${t('scene.title').replace(/🏔️\s?/, '')}`, `
    <div class="edit-field"><label>ID</label><input id="ns-id" placeholder="a-z, 0-9, _-"></div>
    <div class="edit-field"><label>${t('scene.name')}</label><input id="ns-name"></div>
    <div class="edit-field"><label>${t('scene.desc')}</label><textarea id="ns-desc" rows="3"></textarea></div>
    <div class="edit-field"><label>${t('scene.lighting')}</label><input id="ns-lighting"></div>`, `saveNewScene()`);
}
async function saveNewScene() {
  const id = val('ns-id');
  if (!id || !/^[a-zA-Z0-9_-]+$/.test(id)) { toast('ID invalid', 'error'); return; }
  try {
    await api('/scenes', { method: 'POST', body: {
      id, name: val('ns-name'), description: val('ns-desc'), lighting: val('ns-lighting'),
    }});
    invalidateCache('scenes'); document.getElementById('new-scene-overlay')?.remove(); toast(t('toast.created')); loadScenes();
  } catch (e) { toast(e.message, 'error'); }
}
function deleteScene(id) { _crudDelete('scenes', id, t('scene.title').replace(/🏔️\s?/, ''), loadScenes); }

async function editScene(id) {
  const s = ((await cachedFetch('scenes', () => api('/scenes'))).scenes || []).find(x => x.id === id);
  if (!s) { toast(t('scene.not_found'), 'error'); return; }
  _showOverlay('edit-scene-overlay', `${t('scene.edit_title')} ${id}`, `
    <div class="edit-field"><label>${t('scene.name')}</label><input id="es-name" value="${esc(s.name || '')}"></div>
    <div class="edit-field"><label>${t('scene.desc')}</label><textarea id="es-desc" rows="3">${esc(s.description || '')}</textarea></div>
    <div class="edit-field"><label>${t('scene.lighting')}</label><input id="es-lighting" value="${esc(s.lighting || '')}"></div>`, `saveSceneEdit('${id}')`);
}
function saveSceneEdit(id) { _crudSave('scenes', id, () => ({ name: val('es-name'), description: val('es-desc'), lighting: val('es-lighting') }), 'edit-scene-overlay', loadScenes); }

// ── DOM 取值快捷 ──
function val(id) { return document.getElementById(id)?.value || ''; }

// ══════════════════════════════════════════════════════════
// 分镜表
// ══════════════════════════════════════════════════════════

const SB_FIELDS = ['scene', 'characters', 'action', 'dialogue', 'camera', 'shot_type', 'duration', 'emotion'];

async function loadStoryboard() {
  const el = document.getElementById('page-storyboard');
  try {
    const episodes = await loadEpisodeSelector();
    const d = await cachedFetch(`storyboard/${ep}`, () => api(`/storyboard/${ep}`));
    const ss = d.shots || [];
    const rows = ss.map((s, i) => `<tr>
      <td>${_shotId(s, i)}</td>
      ${SB_FIELDS.slice(0, 4).map(f => `<td><input class="sb-inline-input" value="${esc(s[f] || '')}" data-idx="${i}" data-field="${f}" onchange="updateShotField(this)"></td>`).join('')}
      <td><select class="sb-inline-input" data-idx="${i}" data-field="camera" onchange="updateShotField(this)">${_selectOpts(CAMERAS, s.camera)}</select></td>
      <td><select class="sb-inline-input" data-idx="${i}" data-field="shot_type" onchange="updateShotField(this)">${_selectOpts(SHOT_TYPES, s.shot_type)}</select></td>
      <td><input class="sb-inline-input" type="number" value="${s.duration || 4}" min="1" max="30" data-idx="${i}" data-field="duration" onchange="updateShotField(this)"></td>
      <td><select class="sb-inline-input" data-idx="${i}" data-field="emotion" onchange="updateShotField(this)">${_selectOpts(EMOTIONS, s.emotion)}</select></td>
      <td><button class="btn btn-xs btn-danger" onclick="deleteShotFromSB(${i})">🗑️</button></td></tr>`).join('');
    const epSelector = _episodeSelectHtml(episodes, 'switchEpisode');
    el.innerHTML = `<div class="card"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem"><h2>${t('sb.title')}</h2>
      <div style="display:flex;gap:0.5rem;align-items:center">${epSelector}<button class="btn btn-primary" onclick="navTo('pipeline')">🎬 ${t('nav.pipeline').replace('🎬 ', '')}</button><button class="btn btn-success" onclick="addShot()">+ ${t('btn.add').replace('+ ', '')}</button></div></div>
      <div style="overflow-x:auto"><table><thead><tr><th>${t('sb.shot_id')}</th><th>${t('edit.scene')}</th><th>${t('edit.characters')}</th><th>${t('edit.action')}</th><th>${t('edit.dialogue')}</th><th>${t('edit.camera')}</th><th>${t('edit.shot_type')}</th><th>${t('edit.duration')}</th><th>${t('sb.emotion')}</th><th></th></tr></thead>
      <tbody>${rows || `<tr><td colspan="10" class="dim" style="text-align:center">${t('sb.none')}</td></tr>`}</tbody></table></div></div>`;
  } catch (e) { el.innerHTML = `<div class="card"><h2>${t('common.error')}</h2><p>${esc(e.message)}</p></div>`; }
}

let _sbDirty = false;
const _debouncedSaveSB = debounce(async () => {
  if (!_sbDirty) return;
  try {
    const current = (await api(`/storyboard/${ep}`)).shots || [];
    document.querySelectorAll('.sb-inline-input').forEach(inp => { const i = parseInt(inp.dataset.idx); if (current[i]) current[i][inp.dataset.field] = inp.value; });
    await api(`/storyboard/${ep}`, { method: 'POST', body: { shots: current } }); invalidateCache(`storyboard/${ep}`); _sbDirty = false; toast(t('toast.saved'));
  } catch (e) { toast(e.message, 'error'); }
}, 1000);
function updateShotField() { _sbDirty = true; _debouncedSaveSB(); }

async function deleteShotFromSB(idx) {
  const current = (await api(`/storyboard/${ep}`)).shots || [];
  if (!confirm(t('confirm.delete_shot', { id: current[idx]?.shot_id || idx + 1 }))) return;
  pushUndo(`删除镜头 ${current[idx]?.shot_id || idx + 1}`); current.splice(idx, 1);
  try { await api(`/storyboard/${ep}`, { method: 'POST', body: { shots: current } }); invalidateCache(`storyboard/${ep}`); toast(t('toast.deleted')); loadStoryboard(); } catch (e) { toast(e.message, 'error'); }
}

async function addShot() {
  const existing = (await api(`/storyboard/${ep}`)).shots || [];
  const maxNum = Math.max(0, ...existing.map(s => parseInt(s.shot_id, 10)).filter(n => !isNaN(n)));
  const newId = String(maxNum + 1).padStart(3, '0');
  pushUndo(`添加镜头 ${newId}`);
  try { await api(`/storyboard/${ep}`, { method: 'POST', body: { shots: [...existing, { episode: ep, shot_id: newId, scene: '', characters: '', action: '', dialogue: '', camera: CAMERAS[0], shot_type: SHOT_TYPES[2], duration: 4, emotion: 'neutral', outfit: '', action_en: '', dialogue_en: '' }] } }); invalidateCache(`storyboard/${ep}`); toast(t('toast.created')); loadStoryboard(); } catch (e) { toast(e.message, 'error'); }
}

// ══════════════════════════════════════════════════════════
// 项目管理
// ══════════════════════════════════════════════════════════

async function loadProjects() {
  const el = document.getElementById('page-projects');
  el.innerHTML = `<div class="card"><h2>${t('common.loading')}</h2></div>`;
  try {
    const d = await api('/projects');
    const rows = (d.projects || []).map(p => `<tr><td>${p.active ? '→' : ''}</td><td>${p.name}</td><td class="dim" style="font-size:0.75rem">${p.path}</td><td>${p.active ? `<span class="badge badge-green">${t('common.current')}</span>` : `<button class="btn btn-sm btn-primary" onclick="switchProj('${p.name}')">${t('common.switch')}</button> <button class="btn btn-sm btn-danger" onclick="deleteProj('${p.name}')">🗑️</button>`}</td></tr>`).join('');
    el.innerHTML = `<div class="card"><div style="display:flex;justify-content:space-between;margin-bottom:1rem"><h2>${t('proj.title')}</h2><button class="btn btn-success" onclick="newProj()">+ ${t('btn.add').replace('+ ', '')}</button></div>
      <table><thead><tr><th></th><th>${t('common.name')}</th><th>${t('common.path')}</th><th>${t('common.status')}</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  } catch (e) { el.innerHTML = `<div class="card"><h2>${t('common.error')}</h2><p>${esc(e.message)}</p></div>`; }
}
function newProj() { const n = prompt(t('proj.input_name')); if (!n) return; api('/projects/new', { method: 'POST', body: { name: n } }).then(() => { toast(t('toast.created')); loadProjects(); }).catch(e => toast(e.message, 'error')); }
function switchProj(n) { api('/projects/switch', { method: 'POST', body: { name: n } }).then(() => { toast(t('toast.switched')); loadProjects(); }).catch(e => toast(e.message, 'error')); }
function deleteProj(n) { if (!confirm(t('proj.confirm_delete', { name: n }))) return; api(`/projects/${encodeURIComponent(n)}`, { method: 'DELETE' }).then(() => { toast(t('proj.deleted')); loadProjects(); }).catch(e => toast(e.message, 'error')); }

// ══════════════════════════════════════════════════════════
// 系统设置
// ══════════════════════════════════════════════════════════

function _backendSection(label, icon, idPrefix, backends, backend, url, available, reason) {
  return `<div class="config-section"><h3>${icon} ${label}</h3>
    <div class="form-row"><label>${t('set.backend')}</label><select id="cfg-${idPrefix}" onchange="_updateUrl('${idPrefix}')">${backends.map(b => `<option value="${b}" ${backend === b ? 'selected' : ''}>${b}</option>`).join('')}</select></div>
    <div class="form-row"><label>${t('set.address')}</label><input id="cfg-${idPrefix}-url" value="${esc(url)}"></div>
    <div class="tool-status-inline"><span class="status-dot ${available ? 'ok' : 'err'}"></span>${available ? t('dash.available') : reason || t('dash.unavailable')}</div></div>`;
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
    const tools = td.tools || {}, lang = localStorage.getItem('drama_lang') || 'zh';
    const tts = _resolveBackendUrl(cfg, 'tts'), ls = _resolveBackendUrl(cfg, 'lip_sync');
    el.innerHTML = `
      <div class="card"><h2>🌐 语言 / Language</h2><div class="form-row"><label>Language</label>
        <select id="cfg-lang" onchange="setLang(this.value);loadSettings()"><option value="zh" ${lang === 'zh' ? 'selected' : ''}>中文</option><option value="en" ${lang === 'en' ? 'selected' : ''}>English</option></select></div></div>
      <div class="card"><h2>💻 ${t('set.env')}</h2><div class="info-grid"><div><span class="dim">${t('set.os')}:</span> ${env.os}</div><div><span class="dim">${t('set.python')}:</span> ${env.python}</div><div><span class="dim">${t('set.gpu')}:</span> ${env.gpu.available ? env.gpu.name + ' (' + env.gpu.vram_mb + 'MB)' : t('set.gpu_unavailable')}</div></div></div>
      <div class="card"><h2>🔧 ${t('set.config')}</h2>
        ${_backendSection(t('set.tts'), '🎤', 'tts', ['mimo-voicedesign', 'mimo-voiceclone', 'gpt-sovits', 'cosyvoice', 'fish-speech'], tts.backend, tts.url, tools.tts?.available, tools.tts?.reason)}
        ${_backendSection(t('set.lipsync'), '👄', 'lipsync', ['musetalk', 'sadtalker', 'wav2lip'], ls.backend, ls.url, tools.lipsync?.available, tools.lipsync?.reason)}
        <div class="config-section"><h3>🎨 ComfyUI</h3>
          <div class="form-row"><label>${t('set.address')}</label><input id="cfg-comfyui" value="${esc(cfg.comfyui?.url || '')}"></div>
          <div class="tool-status-inline"><span class="status-dot ${tools.comfyui?.available ? 'ok' : 'err'}"></span>${tools.comfyui?.available ? t('dash.available') : tools.comfyui?.reason || t('dash.unavailable')}</div></div>
        <div class="config-section"><h3>⚡ ${t('batch.concurrent')}</h3>
          <div class="form-row"><label>${t('batch.concurrent')}</label><select id="cfg-concurrency" onchange="localStorage.setItem('drama_concurrency',this.value)">
            <option value="1" ${(localStorage.getItem('drama_concurrency')||'1')==='1'?'selected':''}>1 (串行)</option>
            <option value="2" ${localStorage.getItem('drama_concurrency')==='2'?'selected':''}>2</option>
            <option value="3" ${localStorage.getItem('drama_concurrency')==='3'?'selected':''}>3</option>
            <option value="5" ${localStorage.getItem('drama_concurrency')==='5'?'selected':''}>5</option>
          </select></div></div>
        <button class="btn btn-primary" style="margin-top:1rem" onclick="saveCfg()">💾 ${t('btn.save').replace('💾 ', '')}</button></div>`;
  } catch (e) { el.innerHTML = `<div class="card"><h2>${t('common.error')}</h2><p>${esc(e.message)}</p></div>`; }
}

async function saveCfg() {
  try {
    const cfg = await api('/config'); cfg.models = cfg.models || {};
    for (const [prefix, idPrefix] of [['tts', 'tts'], ['lip_sync', 'lipsync']]) {
      const backend = val(`cfg-${idPrefix}`); cfg.models[`${prefix}_backend`] = backend;
      const key = backend.replace(/-/g, '_'); cfg.models[key] = cfg.models[key] || {}; cfg.models[key].api_url = val(`cfg-${idPrefix}-url`);
    }
    cfg.comfyui = cfg.comfyui || {}; cfg.comfyui.url = val('cfg-comfyui');
    await api('/config', { method: 'POST', body: cfg }); toast(t('toast.saved'));
  } catch (e) { toast(e.message, 'error'); }
}

applyI18n();
loadDashboard();

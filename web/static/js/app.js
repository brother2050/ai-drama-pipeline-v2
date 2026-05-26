// AI 短剧工作台 v2
const API = '/api';

// ── 基础设施 ──

const _cache = new Map();
const CACHE_TTL = 30000;
const MAX_UNDO = 50;
const MAX_POLL = 300;

let ep = 1, shots = [], batchCancelled = false;
const _undoStack = [], _redoStack = [];
let _currentTaskId = null; // 当前正在执行的任务 ID

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

async function addEpisode() {
  const input = await modalPrompt(t('ep.input'), '', { inputType: 'number', placeholder: '1' });
  if (!input) return;
  const newEp = parseInt(input);
  if (!newEp || newEp < 1) { toast(t('ep.invalid'), 'error'); return; }
  ep = newEp;
  invalidateCache('episodes');
  invalidateCache(`storyboard/${ep}`);
  const p = document.querySelector('.page.active');
  if (p?.id === 'page-storyboard') loadStoryboard();
  else if (p?.id === 'page-pipeline') loadPipeline();
  toast(t('ep.switched', { ep }));
}

function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

function debounce(fn, ms = 300) { let _t; return (...a) => { clearTimeout(_t); _t = setTimeout(() => fn(...a), ms); }; }
function toast(msg, type = 'success') { const el = document.createElement('div'); el.className = `toast toast-${type}`; el.textContent = msg; document.body.appendChild(el); setTimeout(() => el.remove(), 3500); }

// ── 简洁工具 ──

/** 安全设置元素 innerHTML（null 则跳过） */
function _html(el, content) { if (el) el.innerHTML = content; }

/** 安全设置按钮加载态 */
function _btnLoad(btn, text) {
  if (!btn) return () => {};
  const orig = btn.innerHTML;
  btn.disabled = true; btn.innerHTML = text; btn.style.opacity = '0.7';
  return () => { btn.disabled = false; btn.innerHTML = orig; btn.style.opacity = ''; };
}

// ── 自定义模态框（替代原生 prompt/confirm）──

function modalConfirm(message) {
  return new Promise(resolve => {
    const o = document.createElement('div'); o.className = 'edit-overlay';
    o.innerHTML = `<div class="edit-panel" style="width:400px"><div class="edit-header"><h3>${t('btn.confirm')}</h3></div>
      <div class="edit-body"><p style="font-size:.88rem;line-height:1.6">${esc(message)}</p></div>
      <div class="edit-footer"><button class="btn btn-primary" id="_mc-ok">${t('btn.confirm')}</button>
      <button class="btn btn-outline" id="_mc-cancel">${t('btn.cancel')}</button></div></div>`;
    document.body.appendChild(o);
    const cleanup = (val) => { o.remove(); resolve(val); };
    o.querySelector('#_mc-ok').onclick = () => cleanup(true);
    o.querySelector('#_mc-cancel').onclick = () => cleanup(false);
    o.onclick = (e) => { if (e.target === o) cleanup(false); };
    o.querySelector('#_mc-ok').focus();
  });
}

function modalPrompt(message, defaultValue = '', opts = {}) {
  return new Promise(resolve => {
    const o = document.createElement('div'); o.className = 'edit-overlay';
    const inputTag = opts.type === 'select'
      ? `<select id="_mp-input">${(opts.options||[]).map(v => `<option ${v===defaultValue?'selected':''}>${v}</option>`).join('')}</select>`
      : opts.type === 'textarea'
      ? `<textarea id="_mp-input" rows="4" style="width:100%" ${opts.placeholder?`placeholder="${esc(opts.placeholder)}"`:''}>${esc(defaultValue)}</textarea>`
      : `<input id="_mp-input" type="${opts.inputType||'text'}" value="${esc(defaultValue)}" ${opts.placeholder?`placeholder="${esc(opts.placeholder)}"`:''}>`;
    o.innerHTML = `<div class="edit-panel" style="width:400px"><div class="edit-header"><h3>${esc(message)}</h3></div>
      <div class="edit-body"><div class="edit-field">${inputTag}</div></div>
      <div class="edit-footer"><button class="btn btn-primary" id="_mp-ok">${t('btn.confirm')}</button>
      <button class="btn btn-outline" id="_mp-cancel">${t('btn.cancel')}</button></div></div>`;
    document.body.appendChild(o);
    const inp = o.querySelector('#_mp-input');
    const cleanup = (val) => { o.remove(); resolve(val); };
    o.querySelector('#_mp-ok').onclick = () => cleanup(inp.value);
    o.querySelector('#_mp-cancel').onclick = () => cleanup(null);
    o.onclick = (e) => { if (e.target === o) cleanup(null); };
    inp.focus(); inp.select();
    inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') cleanup(inp.value); if (e.key === 'Escape') cleanup(null); });
  });
}

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
  item.onclick = async () => {
    // 检查分镜表是否有未保存的修改
    if (_sbDirty) {
      const ok = await modalConfirm(t('sb.unsaved_confirm'));
      if (!ok) return;
      _sbDirty = false;
    }
    document.querySelectorAll('.nav-item,.page').forEach(el => el.classList.remove('active'));
    item.classList.add('active');
    document.getElementById(`page-${item.dataset.page}`).classList.add('active');
    loadPage(item.dataset.page);
  };
});
function navTo(p) { document.querySelector(`.nav-item[data-page="${p}"]`).click(); }
const PAGES = { dashboard: loadDashboard, characters: loadCharacters, scenes: loadScenes, storyboard: loadStoryboard, pipeline: loadPipeline, projects: loadProjects, settings: loadSettings, seko: loadSeko, assets: loadAssets };
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
    <h2>${title}</h2><button class="btn btn-success" onclick="${newFn}()">+ ${t('btn.add')}</button></div>${table}${hint}</div>`;
}

async function _crudDelete(endpoint, id, label, reload) {
  if (!await modalConfirm(`${label} ${id}？`)) return;
  try { await api(`/${endpoint}/${id}`, { method: 'DELETE' }); invalidateCache(endpoint); toast(t('toast.deleted')); reload(); } catch (e) { toast(e.message, 'error'); }
}
async function _crudSave(endpoint, id, fieldsFn, overlayId, reload) {
  try { await api(`/${endpoint}`, { method: 'POST', body: { id, ...fieldsFn() } }); invalidateCache(endpoint); document.getElementById(overlayId)?.remove(); toast(t('toast.saved')); reload(); } catch (e) { toast(e.message, 'error'); }
}

function _showOverlay(id, title, bodyHtml, saveFn, saveLabel, deleteFn) {
  const btnText = saveLabel || `💾 ${t('btn.save')}`;
  const deleteBtn = deleteFn ? `<button class="btn btn-danger" onclick="${deleteFn}" style="margin-right:auto">🗑️ ${t('btn.delete')}</button>` : '';
  const o = document.createElement('div'); o.className = 'edit-overlay'; o.id = id;
  o.innerHTML = `<div class="edit-panel"><div class="edit-header"><h3>${esc(title)}</h3>
    <button class="btn btn-sm btn-outline" onclick="document.getElementById('${id}')?.remove()">✕</button></div>
    <div class="edit-body">${bodyHtml}</div><div class="edit-footer">
    ${deleteBtn}<button class="btn btn-primary" onclick="${saveFn}">${btnText}</button>
    <button class="btn btn-outline" onclick="document.getElementById('${id}')?.remove()">${t('btn.cancel')}</button></div></div>`;
  document.body.appendChild(o);
  o.querySelector('input,textarea')?.focus();
}

// ══════════════════════════════════════════════════════════
// 仪表盘
// ══════════════════════════════════════════════════════════

const TOOL_META = { redis:{icon:'🔴',label:'Redis'}, celery:{icon:'🔧',label:'Celery'}, ffmpeg:{icon:'🎞️',label:'FFmpeg'}, tts:{icon:'🎤',label:'TTS'}, comfyui:{icon:'🎨',label:'ComfyUI'}, lipsync:{icon:'👄',label:'LipSync'}, llm:{icon:'🧠',label:'LLM'}, music:{icon:'🎵',label:'Music'}, seko:{icon:'🎬',label:'Seko'}, training:{icon:'🏋️',label:'Training'} };

async function loadDashboard() {
  const el = document.getElementById('page-dashboard');
  try {
    const [s, projData, sbData] = await Promise.all([
      cachedFetch('system/status', () => api('/system/status'), 10000),
      api('/projects').catch(() => ({ projects: [] })),
      api(`/storyboard/${ep}`).catch(() => ({ shots: [] })),
    ]);
    const tools = s.tools || {};
    const okCount = Object.values(tools).filter(t => t.available).length;
    const totalCount = Object.keys(tools).length;
    const shots = sbData.shots || [];
    const projects = projData.projects || [];
    const currentProj = projects.find(p => p.active) || projects[0];

    // 工具状态分组
    const groups = [
      { label: t('dash.infra'), keys: ['redis', 'celery', 'ffmpeg'] },
      { label: t('dash.ai_tools'), keys: ['tts', 'music', 'seko', 'training'] },
      { label: t('dash.gpu_tools'), keys: ['comfyui', 'lipsync', 'llm'] },
    ];
    let toolHtml = '';
    for (const g of groups) {
      toolHtml += `<div class="section-label">${g.label}</div><div class="tool-grid">`;
      for (const k of g.keys) {
        const info = tools[k] || {}, meta = TOOL_META[k] || {};
        toolHtml += `<div class="tool-card ${info.available ? 'tool-ok' : 'tool-off'}"><span>${meta.icon} ${meta.label}</span>
          <span class="status-dot ${info.available ? 'ok' : 'err'}"></span>
          <span class="dim" style="font-size:0.75rem">${info.available ? t('dash.available') : info.reason || t('dash.unavailable')}</span></div>`;
      }
      toolHtml += '</div>';
    }

    el.innerHTML = `
      <div class="dash-hero">
        <h1>🎬 ${currentProj?.name || t('app.title')}</h1>
        <p>${t('dash.welcome_desc')}</p>
        <div class="inspire-box">
          <textarea id="dash-inspire-input" class="inspire-input" rows="3" placeholder="${esc(t('dash.inspire_placeholder'))}"></textarea>
          <div class="inspire-footer">
            <div class="inspire-options">
              <label class="inspire-toggle" onclick="document.getElementById('inspire-adv').classList.toggle('open')">${t('dash.inspire_advanced')}</label>
              <div id="inspire-adv" class="inspire-advanced">
                <div class="inspire-adv-row">
                  <label>${t('dash.inspire_ep')}</label>
                  <input id="dash-inspire-ep" type="number" value="${ep}" min="1" style="width:60px">
                  <label>${t('dash.inspire_dur')}</label>
                  <input id="dash-inspire-dur" type="number" value="90" min="10" max="600" style="width:80px">
                </div>
                <label class="inspire-check"><input type="checkbox" id="dash-inspire-append"> ${t('dash.inspire_append')}</label>
              </div>
            </div>
            <button class="btn btn-ai btn-inspire" id="dash-inspire-btn" onclick="dashInspireGen()">${t('dash.inspire_btn')}</button>
          </div>
          <div id="dash-inspire-status" class="inspire-status"></div>
        </div>
        <div class="dash-hero-actions">
          <button class="btn btn-primary" onclick="navTo('storyboard')">📝 ${t('nav.storyboard')}</button>
          <button class="btn btn-outline" onclick="navTo('pipeline')">🎬 ${t('nav.pipeline')}</button>
          <button class="btn btn-outline btn-ai" onclick="navTo('storyboard');setTimeout(()=>showAIGenStoryboard(),300)">🤖 ${t('dash.ai_gen')}</button>
        </div>
      </div>

      <div class="stat-grid">
        <div class="stat-card"><div class="stat-icon">📂</div><div class="stat-value">${projects.length}</div><div class="stat-label">${t('dash.stat_projects')}</div></div>
        <div class="stat-card"><div class="stat-icon">🎬</div><div class="stat-value">${shots.length}</div><div class="stat-label">${t('dash.stat_shots')}</div></div>
        <div class="stat-card"><div class="stat-icon">🔧</div><div class="stat-value">${okCount}/${totalCount}</div><div class="stat-label">${t('dash.stat_tools')}</div></div>
        <div class="stat-card"><div class="stat-icon">📅</div><div class="stat-value">${ep}</div><div class="stat-label">${t('dash.stat_episode')}</div></div>
      </div>

      <div class="card"><h2>⚡ ${t('dash.quick_actions')}</h2>
        <div class="quick-entry-grid">
          <div class="quick-entry" onclick="navTo('storyboard')"><span class="quick-entry-icon">📝</span><div><div class="quick-entry-text">${t('nav.storyboard')}</div><div class="quick-entry-desc">${t('dash.qe_storyboard')}</div></div></div>
          <div class="quick-entry" onclick="navTo('characters')"><span class="quick-entry-icon">👤</span><div><div class="quick-entry-text">${t('nav.characters')}</div><div class="quick-entry-desc">${t('dash.qe_characters')}</div></div></div>
          <div class="quick-entry" onclick="navTo('scenes')"><span class="quick-entry-icon">🏔️</span><div><div class="quick-entry-text">${t('nav.scenes')}</div><div class="quick-entry-desc">${t('dash.qe_scenes')}</div></div></div>
          <div class="quick-entry" onclick="navTo('pipeline')"><span class="quick-entry-icon">🎬</span><div><div class="quick-entry-text">${t('nav.pipeline')}</div><div class="quick-entry-desc">${t('dash.qe_pipeline')}</div></div></div>
          <div class="quick-entry" onclick="navTo('projects')"><span class="quick-entry-icon">📂</span><div><div class="quick-entry-text">${t('nav.projects')}</div><div class="quick-entry-desc">${t('dash.qe_projects')}</div></div></div>
          <div class="quick-entry" onclick="navTo('settings')"><span class="quick-entry-icon">⚙️</span><div><div class="quick-entry-text">${t('nav.settings')}</div><div class="quick-entry-desc">${t('dash.qe_settings')}</div></div></div>
        </div>
      </div>

      <div class="card"><h2>${t('dash.title')}</h2>${toolHtml}</div>`;
  } catch (e) { el.innerHTML = `<div class="card"><h2>${t('dash.conn_fail')}</h2><p>${esc(e.message)}</p></div>`; }
}

// ── 灵感生成（一键从大纲生成分镜）──

async function dashInspireGen() {
  const input = document.getElementById('dash-inspire-input');
  const outline = input?.value?.trim();
  if (!outline || outline.length < 10) { toast('请输入至少 10 字的剧情灵感', 'error'); input?.focus(); return; }
  const episode = parseInt(document.getElementById('dash-inspire-ep')?.value) || ep;
  const duration = parseInt(document.getElementById('dash-inspire-dur')?.value) || 90;
  const append = document.getElementById('dash-inspire-append')?.checked || false;
  const statusEl = document.getElementById('dash-inspire-status');
  const reset = _btnLoad(document.getElementById('dash-inspire-btn'), '⏳ AI 生成中...');

  try {
    const { task_id } = await api('/llm/storyboard', { method: 'POST', body: { episode, outline, duration, append } });
    const result = await pollTask(task_id, info => {
      _html(statusEl, `<div class="inspire-progress"><div class="batch-bar"><div class="batch-fill" style="width:${info.progress || 0}%"></div></div><span>⏳ ${info.message || 'AI 生成中...'} (${info.progress || 0}%)</span></div>`);
    });

    if (result.status === 'success' && result.result?.status === 'done') {
      const r = result.result;
      _html(statusEl, `✅ 生成 ${r.count} 个镜头，共 ${r.total_duration} 秒`);
      toast(`✅ 已生成 ${r.count} 个镜头`);
      invalidateCache(`storyboard/${episode}`);
      invalidateCache('episodes');
      setTimeout(() => { ep = episode; navTo('storyboard'); }, 1200);
    } else {
      const err = result.result?.reason || result.error || '生成失败';
      _html(statusEl, `❌ ${err}`);
      toast(`❌ ${err}`, 'error');
    }
  } catch (e) {
    _html(statusEl, `❌ ${e.message}`);
    toast(`❌ ${e.message}`, 'error');
  }
  reset();
}

// ══════════════════════════════════════════════════════════
// 生产工作台
// ══════════════════════════════════════════════════════════

function _updatePipelineStep(step, state) {
  // state: 'active' | 'done' | 'fail' | ''
  const el = document.getElementById(`pf-${step}`);
  if (!el) return;
  el.classList.remove('active', 'done', 'fail');
  if (state) el.classList.add(state);
  // 箭头联动：完成时标记前一段箭头
  const steps = ['tts', 'first-frame', 'video', 'lipsync', 'post'];
  const idx = steps.indexOf(step);
  const arrows = document.querySelectorAll('.pipeline-arrow');
  if (state === 'done' && idx > 0 && arrows[idx - 1]) arrows[idx - 1].classList.add('done');
}

function _resetPipelineSteps() {
  document.querySelectorAll('.pipeline-step').forEach(el => el.classList.remove('active', 'done', 'fail'));
  document.querySelectorAll('.pipeline-arrow').forEach(el => el.classList.remove('done'));
}

const _stepBtns = () => [
  { step: 'tts', icon: '🎤', label: t('step.tts') },
  { step: 'first-frame', icon: '🎨', label: t('step.first_frame') },
  { step: 'video', icon: '🎬', label: t('step.video') },
  { step: 'lipsync', icon: '👄', label: t('step.lipsync') },
];

function _shotId(s, i) { return s.shot_id || String(i + 1).padStart(3, '0'); }
function _actionBtns(idx) {
  return `<button class="btn btn-xs" onclick="editShot(${idx})" title="${t('btn.edit')}">✏️</button>` +
    _stepBtns().map(b => `<button class="btn btn-xs" onclick="runOne('${b.step}',${idx})" title="${b.label}">${b.icon}</button>`).join('') +
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

  // 流程图
  const flowSteps = [
    { icon: '🎤', label: t('step.tts'), step: 'tts' },
    { icon: '🎨', label: t('step.first_frame'), step: 'first-frame' },
    { icon: '🎬', label: t('step.video'), step: 'video' },
    { icon: '👄', label: t('step.lipsync'), step: 'lipsync' },
    { icon: '🎞️', label: t('wb.post_short'), step: 'post' },
  ];
  const flowHtml = `<div class="pipeline-flow">${flowSteps.map((s, i) => {
    const arrow = i < flowSteps.length - 1 ? '<div class="pipeline-arrow"></div>' : '';
    return `<div class="pipeline-step" id="pf-${s.step}"><div class="pipeline-step-icon">${s.icon}</div><div class="pipeline-step-label">${s.label}</div></div>${arrow}`;
  }).join('')}</div>`;

  el.innerHTML = `<div class="wb-top-bar"><div style="display:flex;align-items:center;gap:0.5rem"><h2>🎬 ${t('nav.pipeline')}</h2>${epSelector}<span class="dim" style="font-size:.85rem">${shots.length} ${t('wb.shots_count')}</span></div>
    <div class="wb-batch-btns">
      <button class="btn btn-outline" onclick="undo()" title="Ctrl+Z">↩ ${t('undo.undo')}</button>
      <button class="btn btn-outline" onclick="redo()" title="Ctrl+Shift+Z">↪ ${t('undo.redo')}</button>
      ${_stepBtns().map(b => `<button class="btn btn-outline" onclick="batchRun('${b.step}')">${b.icon} ${t('wb.batch_label')} ${b.label}</button>`).join('')}
      <span class="dim" style="margin:0 0.3rem">|</span>
      <button class="btn btn-outline" onclick="runPortraits()">📸 ${t('wb.gen_portraits')}</button>
      <button class="btn btn-outline" onclick="runPost()">🎞️ ${t('wb.post_process')}</button>
      <button class="btn btn-outline" onclick="runMusic()">🎵 ${t('wb.gen_music')}</button>
      <button class="btn btn-outline" onclick="runSubtitle()">📝 ${t('wb.gen_subtitle')}</button>
      <button class="btn btn-primary" onclick="runAll()">🚀 ${t('wb.run_all')}</button>
    </div></div>
    <div class="card" style="margin-bottom:.7rem"><h2>${t('wb.flow_title')}</h2>${flowHtml}</div>
    <div id="wb-shots-grid" class="wb-shots-grid"></div>
    <div id="wb-batch-status" class="wb-batch-status" style="display:none"></div>
    <div class="card" style="margin-top:.7rem"><h2>${t('wb.final_preview')}</h2><div id="final-preview-area"></div></div>`;
  _resetPipelineSteps();
  renderShotsGrid();
  _loadFinalPreview();
  // Chat FAB
  if (!document.getElementById('chat-fab')) {
    const fab = document.createElement('button');
    fab.id = 'chat-fab';
    fab.className = 'chat-fab';
    fab.textContent = '💬';
    fab.title = t('chat.title');
    fab.onclick = toggleChat;
    document.body.appendChild(fab);
  }
}

function renderShotsGrid() {
  const grid = document.getElementById('wb-shots-grid');
  if (!grid) return;
  grid.innerHTML = shots.map((s, i) => {
    const sid = _shotId(s, i);
    return `<div class="wb-shot-card" id="shot-${esc(sid)}">
      <div class="wb-shot-head" id="shot-head-${esc(sid)}"><span class="wb-shot-num">${esc(sid)}</span><span class="wb-shot-char">${esc(s.characters || '')}</span><span class="wb-shot-scene">${esc(s.scene || '')}</span><span class="wb-shot-status"></span></div>
      <div class="wb-shot-body"><div class="wb-shot-text"><div class="wb-shot-action" title="${esc(s.action || '')}">${esc((s.action || '').substring(0, 30)) || '...'}</div>
        <div class="wb-shot-dialogue" title="${esc(s.dialogue || '')}">"${esc((s.dialogue || '').substring(0, 30)) || '...'}"</div></div>
        <div class="wb-shot-resources" id="res-${esc(sid)}"></div></div>
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
      r.synced && `<div class="res-chip res-synced" onclick="previewRes('${sid}','synced')">👄</div>`,
    ].filter(Boolean).join('');
    el.innerHTML = chips || `<span class="dim" style="font-size:0.7rem">${t('wb.no_resource')}</span>`;
    // 更新卡片头部状态徽章
    const headEl = document.getElementById(`shot-head-${sid}`);
    if (headEl) {
      const st = (k, ok) => `<span class="st ${ok?'st-done':'st-miss'}">${k}</span>`;
      const badgeEl = headEl.querySelector('.wb-shot-status');
      if (badgeEl) badgeEl.innerHTML = st('🎤',r.audio) + st('🎨',r.frame) + st('🎬',r.video) + st('👄',r.synced);
    }
  } catch {}
}

function previewRes(sid, type) {
  const types = ['audio', 'frame', 'video', 'synced'].filter(t => {
    const cls = t === 'frame' ? 'img' : t === 'audio' ? 'audio' : t === 'synced' ? 'synced' : 'video';
    return !!document.querySelector(`#res-${sid} .res-${cls}`);
  });
  let currentType = type;

  function renderOverlay(t) {
    const src = t === 'audio' ? `/api/files/${ep}/${sid}/audio.wav`
      : t === 'frame' ? `/api/files/${ep}/${sid}/frame.png`
      : `/api/files/${ep}/${sid}/${t === 'synced' ? 'synced.mp4' : 'video.mp4'}`;
    const tag = t === 'audio' ? `audio controls src="${src}" style="width:400px"`
      : t === 'frame' ? `img src="${src}" style="max-width:90vw;max-height:80vh;border-radius:8px"`
      : `video controls src="${src}" style="max-width:90vw;max-height:80vh;border-radius:8px"`;
    const idx = types.indexOf(t);
    const nav = types.length > 1 ? `<div style="display:flex;gap:1rem;justify-content:center;margin-top:.6rem">
      ${idx > 0 ? `<button class="btn btn-outline" id="_pr-prev">◀ ${types[idx-1]}</button>` : ''}
      <span class="dim">${idx+1}/${types.length}</span>
      ${idx < types.length-1 ? `<button class="btn btn-outline" id="_pr-next">${types[idx+1]} ▶</button>` : ''}
    </div>` : '';
    return `<div class="res-overlay-inner"><${tag}>${nav}<div class="dim" style="margin-top:0.5rem">${t('wb.esc_hint')}</div></div>`;
  }

  const o = document.createElement('div'); o.className = 'res-overlay';
  o.innerHTML = renderOverlay(currentType);
  o.onclick = (e) => { if (e.target === o) o.remove(); };
  document.body.appendChild(o);

  function switchTo(t) { currentType = t; o.innerHTML = renderOverlay(t); bindNav(); }
  function bindNav() {
    o.querySelector('#_pr-prev')?.addEventListener('click', (e) => { e.stopPropagation(); switchTo(types[types.indexOf(currentType)-1]); });
    o.querySelector('#_pr-next')?.addEventListener('click', (e) => { e.stopPropagation(); switchTo(types[types.indexOf(currentType)+1]); });
  }
  bindNav();

  o._keyHandler = (e) => {
    // 忽略输入框内的方向键（避免冲突）
    if (e.target.matches('input, textarea, select')) return;
    if (e.key === 'ArrowLeft' && types.indexOf(currentType) > 0) switchTo(types[types.indexOf(currentType)-1]);
    if (e.key === 'ArrowRight' && types.indexOf(currentType) < types.length-1) switchTo(types[types.indexOf(currentType)+1]);
  };
  document.addEventListener('keydown', o._keyHandler);
  const origRemove = o.remove.bind(o);
  o.remove = () => { document.removeEventListener('keydown', o._keyHandler); origRemove(); };
}

// ── 镜头编辑 ──

const _cameras = () => [t('camera.fixed'), t('camera.push_in'), t('camera.pan'), t('camera.handheld'), t('camera.orbit'), t('camera.top'), t('camera.bottom')];
const _shotTypes = () => [t('shot.closeup'), t('shot.medium_close'), t('shot.medium'), t('shot.over_shoulder'), t('shot.full'), t('shot.wide'), t('shot.extreme_wide')];
const EMOTIONS = ['neutral', 'happy', 'sad', 'angry', 'worried', 'surprised', 'calm', 'determined'];
const LANGUAGES = [{ value: 'zh', label: '中文' }, { value: 'en', label: 'English' }, { value: 'ja', label: '日本語' }, { value: 'ko', label: '한국어' }, { value: 'fr', label: 'Français' }, { value: 'de', label: 'Deutsch' }, { value: 'es', label: 'Español' }];

// TTS 后端 → 角色 voice 参数字段定义
const TTS_VOICE_FIELDS = {
  'mimo-voicedesign': [{ key: 'voice_description', label: () => t('char.voice_desc'), type: 'textarea' }],
  'mimo-voiceclone': [{ key: 'reference_audio', label: () => t('char.voice_ref_audio'), placeholder: '/path/to/ref.wav' }],
  'gpt-sovits': [{ key: 'reference_audio', label: () => t('char.voice_ref_audio'), placeholder: '/path/to/ref.wav' }, { key: 'prompt_text', label: () => t('char.voice_prompt_text') }],
  'cosyvoice': [{ key: 'speaker', label: () => t('char.voice_speaker'), placeholder: 'default' }],
  'fish-speech': [{ key: 'reference_id', label: () => t('char.voice_ref_id') }],
};

function _selectOpts(options, current) { return options.map(o => `<option ${current === o ? 'selected' : ''}>${o}</option>`).join(''); }

async function editShot(idx) {
  const s = shots[idx], sid = _shotId(shots[idx], idx);
  // 加载角色和场景列表用于下拉选择
  let charOpts = `<option value="">${t('edit.select_char')}</option>`;
  let sceneOpts = `<option value="">${t('edit.select_scene')}</option>`;
  try {
    const [charData, sceneData] = await Promise.all([
      cachedFetch('characters', () => api('/characters')),
      cachedFetch('scenes', () => api('/scenes')),
    ]);
    (charData.characters || []).forEach(c => { charOpts += `<option value="${esc(c.name || c.id)}" ${(s.characters || '').includes(c.name || c.id) ? 'selected' : ''}>${esc(c.name || c.id)}</option>`; });
    (sceneData.scenes || []).forEach(sc => { sceneOpts += `<option value="${esc(sc.name || sc.id)}" ${(s.scene || '') === (sc.name || sc.id) ? 'selected' : ''}>${esc(sc.name || sc.id)}</option>`; });
  } catch {}
  _showOverlay('edit-overlay', `${t('edit.shot_title')} ${sid}`, `
    <div class="edit-field"><label>${t('edit.scene')}</label>
      <div class="edit-field-combo"><select id="ed-scene-sel" onchange="document.getElementById('ed-scene').value=this.value">${sceneOpts}</select><input id="ed-scene" value="${esc(s.scene || '')}" placeholder="${t('edit.select_scene')}"></div></div>
    <div class="edit-field"><label>${t('edit.characters')}</label>
      <div class="edit-field-combo"><select id="ed-chars-sel" onchange="document.getElementById('ed-chars').value=this.value">${charOpts}</select><input id="ed-chars" value="${esc(s.characters || '')}" placeholder="${t('edit.select_char')}"></div></div>
    <div class="edit-field"><label>${t('edit.action')} <span class="char-count" id="cc-action">0</span></label><textarea id="ed-action" rows="2" oninput="updateCharCount('ed-action','cc-action')">${esc(s.action || '')}</textarea></div>
    <div class="edit-field"><label>${t('sb.action_en')} <span class="char-count" id="cc-action-en">0</span></label><textarea id="ed-action-en" rows="2" oninput="updateCharCount('ed-action-en','cc-action-en')">${esc(s.action_en || '')}</textarea></div>
    <div class="edit-field"><label>${t('edit.dialogue')} <span class="char-count" id="cc-dialogue">0</span></label><textarea id="ed-dialogue" rows="2" oninput="updateCharCount('ed-dialogue','cc-dialogue')">${esc(s.dialogue || '')}</textarea></div>
    <div class="edit-field"><label>${t('sb.dialogue_en')} <span class="char-count" id="cc-dialogue-en">0</span></label><textarea id="ed-dialogue-en" rows="2" oninput="updateCharCount('ed-dialogue-en','cc-dialogue-en')">${esc(s.dialogue_en || '')}</textarea></div>
    <div class="edit-field"><label>${t('edit.outfit')}</label><input id="ed-outfit" value="${esc(s.outfit || '')}" placeholder="${t('edit.outfit_ph')}"></div>
    <div class="edit-field-row">
      <div class="edit-field"><label>${t('edit.camera')}</label><select id="ed-camera">${_selectOpts(_cameras(), s.camera)}</select></div>
      <div class="edit-field"><label>${t('edit.shot_type')}</label><select id="ed-shottype">${_selectOpts(_shotTypes(), s.shot_type)}</select></div>
      <div class="edit-field"><label>${t('edit.duration')}</label><input id="ed-dur" type="number" value="${s.duration || 4}" min="1" max="30"></div>
      <div class="edit-field"><label>${t('edit.emotion')}</label><select id="ed-emo">${_selectOpts(EMOTIONS, s.emotion)}</select></div>
      <div class="edit-field"><label>${t('edit.language')}</label><select id="ed-lang">${LANGUAGES.map(l => `<option value="${l.value}" ${(s.language || 'zh') === l.value ? 'selected' : ''}>${l.label}</option>`).join('')}</select></div>
    </div>
    <div class="edit-nav-row">
      ${idx > 0 ? `<button class="btn btn-xs btn-outline" onclick="_saveAndEdit(${idx},${idx-1})">${t('edit.prev_shot')}</button>` : '<span></span>'}
      ${idx < shots.length - 1 ? `<button class="btn btn-xs btn-outline" onclick="_saveAndEdit(${idx},${idx+1})">${t('edit.next_shot')}</button>` : '<span></span>'}
    </div>`, `saveShot(${idx})`);
  // 初始化字数统计
  ['ed-action','ed-action-en','ed-dialogue','ed-dialogue-en'].forEach(id => {
    const el = document.getElementById(id);
    if (el) updateCharCount(id, 'cc-' + id.replace('ed-', ''));
  });
}

function updateCharCount(inputId, countId) {
  const inp = document.getElementById(inputId);
  const cnt = document.getElementById(countId);
  if (inp && cnt) cnt.textContent = t('edit.char_count', { count: inp.value.length });
}

const _SHOT_FIELDS = [['scene', 'ed-scene'], ['characters', 'ed-chars'], ['action', 'ed-action'], ['action_en', 'ed-action-en'], ['dialogue', 'ed-dialogue'], ['dialogue_en', 'ed-dialogue-en'], ['outfit', 'ed-outfit'], ['camera', 'ed-camera'], ['shot_type', 'ed-shottype'], ['duration', 'ed-dur'], ['emotion', 'ed-emo'], ['language', 'ed-lang']];

/** 从编辑面板读取字段值到 shots[idx] */
function _collectShotFields(idx) {
  const s = shots[idx];
  const _defaults = { duration: 4, emotion: 'neutral', language: 'zh' };
  for (const [k, id] of _SHOT_FIELDS)
    s[k] = document.getElementById(id)?.value || _defaults[k] || '';
  return s;
}

/** 保存 shots 到后端并刷新缓存 */
async function _persistShots() {
  await api(`/storyboard/${ep}`, { method: 'POST', body: { shots } });
  invalidateCache(`storyboard/${ep}`);
  invalidateCache(`res/${ep}`);
}

async function _saveAndEdit(fromIdx, toIdx) {
  const s = _collectShotFields(fromIdx);
  pushUndo(`${t('edit.shot_title')} ${s.shot_id || fromIdx + 1}`);
  try {
    await _persistShots();
    document.getElementById('edit-overlay')?.remove();
    editShot(toIdx);
  } catch (e) { toast(e.message, 'error'); }
}

async function saveShot(idx) {
  const s = _collectShotFields(idx);
  pushUndo(`${t('edit.shot_title')} ${s.shot_id || idx + 1}`);
  try { await _persistShots(); toast(t('toast.saved')); document.getElementById('edit-overlay')?.remove(); renderShotsGrid(); } catch (e) { toast(e.message, 'error'); }
}

async function deleteShot(idx) {
  const sid = _shotId(shots[idx], idx);
  if (!await modalConfirm(t('confirm.delete_shot', { id: sid }))) return;
  pushUndo(`${t('btn.delete')} ${sid}`); shots.splice(idx, 1);
  try { await api(`/storyboard/${ep}`, { method: 'POST', body: { shots } }); invalidateCache(`storyboard/${ep}`); toast(t('toast.deleted')); renderShotsGrid(); } catch (e) { toast(e.message, 'error'); }
}

// ── 执行 ──

async function runOne(step, idx) {
  const sid = _shotId(shots[idx], idx);
  const act = document.getElementById(`shot-${sid}`)?.querySelector('.wb-shot-actions');
  _html(act, `<span class="run-indicator">⏳ ${step}...</span> <button class="btn btn-xs btn-danger" onclick="cancelCurrentTask()">⏹</button>`);
  _updatePipelineStep(step, 'active');
  try {
    const { task_id } = await api(`/steps/${step}`, { method: 'POST', body: { episode: ep, shot_id: sid } });
    _currentTaskId = task_id;
    const result = await pollTask(task_id, info => _html(act, `<span class="run-indicator">⏳ ${info.message || step} (${info.progress || 0}%)</span> <button class="btn btn-xs btn-danger" onclick="cancelCurrentTask()">⏹</button>`));
    _currentTaskId = null;
    const sub = result.result;
    if (result.status === 'success' && sub?.status !== 'error' && sub?.status !== 'skipped') {
      toast(`✅ ${sid} ${step} ${t('wb.shot_done')}`); _updatePipelineStep(step, 'done');
    } else if (result.status === 'success' && sub?.status === 'skipped') {
      toast(`⏭ ${sid} ${step}: ${sub.reason || t('wb.shot_skip')}`); _updatePipelineStep(step, 'done');
    } else {
      const err = sub?.reason || result.error || t('wb.shot_fail');
      toast(`❌ ${sid} ${step}: ${err}`, 'error'); _updatePipelineStep(step, 'fail');
    }
  } catch (e) { _currentTaskId = null; toast(`❌ ${sid}: ${e.message}`, 'error'); _updatePipelineStep(step, 'fail'); }
  _html(act, _actionBtns(idx));
  invalidateCache(`res/${ep}/${sid}`); loadResources(idx);
}

async function cancelCurrentTask() {
  if (!_currentTaskId) return;
  try { await api(`/tasks/${_currentTaskId}/cancel`, { method: 'POST' }); toast(t('toast.cancelled')); } catch (e) { toast(e.message, 'error'); }
}

function _batchSummary(done, skip, fail, cancelled) {
  return `<div class="batch-done">${cancelled ? t('wb.batch_cancelled') : t('wb.batch_done')} · ${t('wb.batch_ok')} ${done} · ${t('wb.batch_skip')} ${skip} · ${t('wb.batch_fail')} ${fail}
    <button class="btn btn-sm btn-outline" style="margin-left:0.5rem" onclick="this.parentElement.parentElement.style.display='none'">${t('batch.close_btn')}</button></div>`;
}

async function batchRun(step) {
  const names = { tts: t('step.tts'), 'first-frame': t('step.first_frame'), video: t('step.video'), lipsync: t('step.lipsync') };
  if (!await modalConfirm(t('batch.confirm', { step: names[step], n: shots.length }))) return;
  batchCancelled = false;
  _updatePipelineStep(step, 'active');
  const statusEl = document.getElementById('wb-batch-status');
  statusEl.style.display = 'block';
  const concurrency = parseInt(localStorage.getItem('drama_concurrency') || '1');
  let done = 0, fail = 0, skip = 0, idx = 0;

  function _batchProgressHTML(i, sid) {
    return `<div class="batch-progress"><div class="batch-bar"><div class="batch-fill" style="width:${(i / shots.length) * 100}%"></div></div>
      <div class="batch-text">[${i + 1}/${shots.length}] ${sid} — ${t('batch.progress', { step: names[step] })}</div>
      <div style="font-size:.82rem;margin-top:.25rem;color:var(--fg2)">${t('wb.batch_ok')} <b>${done}</b> · ${t('wb.batch_skip')} <b>${skip}</b> · ${t('wb.batch_fail')} <b style="color:${fail?'var(--red)':'inherit'}">${fail}</b></div>
      <button class="btn btn-sm btn-danger" onclick="batchCancelled=true;cancelCurrentTask()" style="margin-top:0.3rem">${t('batch.cancel_btn')}</button></div>`;
  }

  async function processShot(i) {
    if (batchCancelled) return;
    const sid = _shotId(shots[i], i);
    try {
      const { task_id } = await api(`/steps/${step}`, { method: 'POST', body: { episode: ep, shot_id: sid } });
      _currentTaskId = task_id;
      const result = await pollTask(task_id);
      _currentTaskId = null;
      if (result.status === 'success') {
        const sub = result.result;
        if (sub?.status === 'error') fail++;
        else if (sub?.status === 'skipped') skip++;
        else { done++; invalidateCache(`res/${ep}/${sid}`); loadResources(i); }
      } else fail++;
    } catch { _currentTaskId = null; fail++; }
  }

  if (concurrency <= 1) {
    // 串行
    for (let i = 0; i < shots.length; i++) {
      if (batchCancelled) break;
      const sid = _shotId(shots[i], i);
      statusEl.innerHTML = _batchProgressHTML(i, sid);
      await processShot(i);
      statusEl.innerHTML = _batchProgressHTML(i, sid); // 更新计数
    }
  } else {
    // 并发
    const pool = new Set();
    for (let i = 0; i < shots.length; i++) {
      if (batchCancelled) break;
      const sid = _shotId(shots[i], i);
      statusEl.innerHTML = _batchProgressHTML(i, sid);
      const p = processShot(i).then(() => { pool.delete(p); statusEl.innerHTML = _batchProgressHTML(i, sid); });
      pool.add(p);
      if (pool.size >= concurrency) await Promise.race(pool);
    }
    await Promise.all(pool);
  }

  if (batchCancelled) { statusEl.innerHTML = _batchSummary(done, skip, fail, true); toast(t('toast.cancelled')); _updatePipelineStep(step, 'fail'); return; }
  statusEl.innerHTML = _batchSummary(done, skip, fail, false);
  _updatePipelineStep(step, fail > 0 ? 'fail' : 'done');
  toast(t('batch.complete', { done, skip, fail }));
}

// ── 管线工具 ──

async function _runTool(apiPath, body, label) {
  if (!await modalConfirm(label + '?')) return;
  try {
    toast('⏳ ' + label);
    const { task_id } = await api(apiPath, { method: 'POST', body });
    const result = await pollTask(task_id);
    if (result.status === 'success' && result.result?.status !== 'error') toast('✅ ' + label);
    else toast('❌ ' + (result.result?.reason || result.error || t('wb.shot_fail')), 'error');
  } catch (e) { toast('❌ ' + e.message, 'error'); }
}

async function runPortraits() { await _runTool('/tools/portraits', {}, t('wb.gen_portraits')); }
async function runPost() { await _runTool('/tools/post', { episode: ep }, t('wb.post_process')); }

async function runAll() {
  if (!await modalConfirm(t('wb.run_all') + '?')) return;
  const statusEl = document.getElementById('wb-batch-status');
  statusEl.style.display = 'block';
  const stages = ['preview', 'produce', 'post'];
  for (let i = 0; i < stages.length; i++) {
    const cmd = stages[i];
    statusEl.innerHTML = `<div class="batch-progress"><div class="batch-bar"><div class="batch-fill" style="width:${(i / stages.length) * 100}%"></div></div>
      <div class="batch-text">[${i + 1}/${stages.length}] ${cmd}...</div></div>`;
    try {
      const { task_id } = await api('/pipeline/run', { method: 'POST', body: { episode: ep, command: cmd } });
      const result = await pollTask(task_id);
      if (result.status !== 'success') { statusEl.innerHTML = `<div class="batch-done">❌ ${cmd}: ${esc(result.error || t('wb.shot_fail'))}</div>`; return; }
      // 检查子任务返回的实际状态（Celery SUCCESS 不代表业务成功）
      const sub = result.result;
      if (sub?.status === 'error' || sub?.status === 'empty') {
        statusEl.innerHTML = `<div class="batch-done">❌ ${cmd}: ${esc(sub.reason || sub.message || t('wb.shot_fail'))}</div>`; return;
      }
    } catch (e) { statusEl.innerHTML = `<div class="batch-done">❌ ${cmd}: ${esc(e.message)}</div>`; return; }
  }
  statusEl.innerHTML = `<div class="batch-done">✅ ${t('wb.run_all')}</div>`;
  toast('✅ ' + t('wb.run_all'));
  // 刷新资源
  invalidateCache(`storyboard/${ep}`);
  invalidateCache(`res/${ep}`);
  renderShotsGrid();
}

async function runMusic() {
  const duration = await modalPrompt(t('wb.music_duration') + ':', '60', { inputType: 'number' });
  if (!duration) return;
  const mood = await modalPrompt(t('wb.music_mood') + ':', 'neutral');
  await _runTool('/tools/music', { duration: parseFloat(duration), mood: mood || 'neutral' }, t('wb.gen_music'));
}

async function runSubtitle() { await _runTool('/tools/subtitle', { episode: ep }, t('wb.gen_subtitle')); }

// ══════════════════════════════════════════════════════════
// 角色管理
// ══════════════════════════════════════════════════════════

/** 通用实体列表渲染 */
function _loadEntityPage(type, { pageId, icon, titleKey, emptyHintKey, emptyDescKey, editFn, newFn, aiFn, card }) {
  const el = document.getElementById(pageId);
  const addLabel = t('btn.add');
  cachedFetch(type, () => api(`/${type}`)).then(d => {
    const items = d[type] || [];
    const grid = items.length
      ? `<div class="entity-grid">${items.map(it => card(it)).join('')}</div>`
      : `<div class="empty-state"><div class="empty-state-icon">${icon}</div><h3>${t(emptyHintKey)}</h3><p>${t(emptyDescKey)}</p><button class="btn btn-success" onclick="${newFn}()">+ ${addLabel}</button></div>`;
    el.innerHTML = `<div class="card"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem"><h2>${icon} ${t(titleKey)}</h2><div style="display:flex;gap:0.5rem"><button class="btn btn-outline btn-ai" onclick="${aiFn}()">🤖 AI 生成</button><button class="btn btn-success" onclick="${newFn}()">+ ${addLabel}</button></div></div>${grid}</div>`;
  }).catch(e => { el.innerHTML = `<div class="card"><h2>${t('common.error')}</h2><p>${esc(e.message)}</p></div>`; });
}

/** 通用编辑面板 */
function _editEntityPanel(type, id, { titleKey, notFoundKey, fields, imgPrefix, imgLabel, confirmMsg, imgKey = 'reference_images', buildExtra, reload, extraHtml, deleteFn }) {
  const p = imgPrefix;
  api(`/${type}`).then(d => {
    const item = (d[type] || []).find(x => x.id === id);
    if (!item) { toast(t(notFoundKey), 'error'); return; }
    const existingImg = (item[imgKey]?.length)
      ? `<div class="upload-preview"><img src="${esc(item[imgKey][0])}" id="${p}-img-preview"><button class="btn btn-xs btn-danger upload-remove" onclick="${p}RemoveImg('${id}')">✕</button></div>`
      : `<div class="upload-area" id="${p}-upload-area" onclick="document.getElementById('${p}-file').click()" ondragover="event.preventDefault();this.classList.add('dragover')" ondragleave="this.classList.remove('dragover')" ondrop="${p}HandleDrop(event,'${id}')"><span class="upload-icon">📷</span><span>${t('common.upload_hint')}</span></div>`;
    const body = `<div class="edit-field"><label>${imgLabel}</label><div id="${p}-img-wrap">${existingImg}</div><input type="file" id="${p}-file" accept="image/*" style="display:none" onchange="${p}UploadImg('${id}')"></div>` +
      fields.map(f => {
        const v = f.getValue ? f.getValue(item) : (item[f.key] || '');
        if (f.type === 'select') return `<div class="edit-field"><label>${f.label}</label><select id="${p}-${f.key}">${f.options.map(o => `<option value="${o.value}" ${v===o.value?'selected':''}>${o.label}</option>`).join('')}</select></div>`;
        if (f.type === 'textarea') return `<div class="edit-field"><label>${f.label}</label><textarea id="${p}-${f.key}" rows="3">${esc(v)}</textarea></div>`;
        return `<div class="edit-field"><label>${f.label}</label><input id="${p}-${f.key}" value="${esc(v)}"></div>`;
      }).join('') + (typeof extraHtml === 'function' ? extraHtml(item) : (extraHtml || ''));
    window[`_${p}ImgRemoved`] = false;
    const delFn = deleteFn ? `delete_${p}Edit('${id}')` : undefined;
    _showOverlay(`edit-${type.slice(0,-1)}-overlay`, `${t(titleKey)} ${id}`, body, `save_${p}Edit('${id}')`, undefined, delFn);
  }).catch(e => toast(e.message, 'error'));
  window[`save_${p}Edit`] = function(eid) {
    const extra = window[`_${p}ImgRemoved`] ? { [imgKey]: [] } : {};
    window[`_${p}ImgRemoved`] = false;
    const data = buildExtra ? { ...buildExtra(), ...extra } : { ...extra };
    fields.forEach(f => { if (!f.getValue) data[f.key] = $val(`${p}-${f.key}`); });
    _crudSave(type, eid, () => data, `edit-${type.slice(0,-1)}-overlay`, reload);
  };
  if (deleteFn) {
    window[`delete_${p}Edit`] = async function(eid) {
      document.getElementById(`edit-${type.slice(0,-1)}-overlay`)?.remove();
      await deleteFn(eid);
    };
  }
  window[`${p}UploadImg`] = async function(eid) { await _uploadImg(type, eid); };
  window[`${p}HandleDrop`] = function(e, eid) { _handleImgDrop(e, type, eid); };
  window[`${p}RemoveImg`] = async function(eid) {
    if (!await modalConfirm(confirmMsg)) return;
    window[`_${p}ImgRemoved`] = true;
    _html(document.getElementById(`${p}-img-wrap`), `<div class="upload-area" onclick="document.getElementById('${p}-file').click()"><span class="upload-icon">📷</span><span>${t('common.upload_hint')}</span></div>`);
  };
}

async function loadCharacters() {
  _loadEntityPage('characters', {
    pageId: 'page-characters', icon: '👤', titleKey: 'char.title',
    emptyHintKey: 'char.empty_hint', emptyDescKey: 'char.empty_desc',
    editFn: 'editChar', newFn: 'newChar', aiFn: 'showAIGenCharacter',
    card: c => {
      const avatar = c.appearance ? esc(c.appearance.substring(0, 2)) : '👤';
      const thumb = (c.reference_images?.length) ? `<img src="${esc(c.reference_images[0])}" loading="lazy">` : avatar;
      return `<div class="entity-card" onclick="editChar('${esc(c.id)}')"><div class="entity-card-thumb">${thumb}</div><div class="entity-card-body"><h3>${esc(c.name || c.id)}</h3><p>${esc(c.appearance || '')}</p></div><div class="entity-card-footer"><span class="entity-card-id">${esc(c.id)}</span><span>${c.gender === 'male' ? '♂' : c.gender === 'female' ? '♀' : ''} <button class="btn btn-xs btn-danger" onclick="event.stopPropagation();deleteChar('${esc(c.id)}')" title="${t('btn.delete')}">🗑️</button></span></div></div>`;
    }
  });
}
/** 通用新建面板 */
function _newEntityPanel(type, { titleKey, fields, buildExtra, reload, extraHtml }) {
  const p = `n${type[0]}`; // nc / ns
  const body = `<div class="edit-field"><label>ID</label><input id="${p}-id" placeholder="a-z, 0-9, _-"></div>` +
    fields.map(f => {
      if (f.type === 'select') return `<div class="edit-field"><label>${f.label}</label><select id="${p}-${f.key}">${f.options.map(o => `<option value="${o.value}">${o.label}</option>`).join('')}</select></div>`;
      if (f.type === 'textarea') return `<div class="edit-field"><label>${f.label}</label><textarea id="${p}-${f.key}" rows="3"></textarea></div>`;
      return `<div class="edit-field"><label>${f.label}</label><input id="${p}-${f.key}"${f.placeholder ? ` placeholder="${f.placeholder}"` : ''}></div>`;
    }).join('') + (extraHtml || '');
  _showOverlay(`new-${type.slice(0,-1)}-overlay`, `+ ${t(titleKey)}`, body, `save_${p}New()`);
  window[`save_${p}New`] = async function() {
    const id = $val(`${p}-id`);
    if (!id || !/^[a-zA-Z0-9_-]+$/.test(id)) { toast(t('common.id_invalid'), 'error'); return; }
    const data = buildExtra ? { id, ...buildExtra() } : { id };
    fields.forEach(f => { if (!f.getValue) data[f.key] = $val(`${p}-${f.key}`); });
    try {
      await api(`/${type}`, { method: 'POST', body: data });
      invalidateCache(type); document.getElementById(`new-${type.slice(0,-1)}-overlay`)?.remove(); toast(t('toast.created')); reload();
    } catch (e) { toast(e.message, 'error'); }
  };
}

/** 获取当前 TTS 后端名称（缓存） */
async function _getTtsBackend() {
  try {
    const cfg = await cachedFetch('sysconfig', () => api('/system/config'));
    return cfg.models?.tts_backend || 'mimo-voicedesign';
  } catch { return 'mimo-voicedesign'; }
}

/** 构建 TTS 语音参数 HTML 字段 */
function _ttsVoiceFieldsHtml(prefix, voiceData = {}) {
  const backend = _cache.get('sysconfig')?.data?.models?.tts_backend || 'mimo-voicedesign';
  const fields = TTS_VOICE_FIELDS[backend] || TTS_VOICE_FIELDS['mimo-voicedesign'];
  return `<div class="edit-field" style="margin-top:.5rem"><label>⚙️ ${t('char.voice_params')} <span class="dim" style="font-size:.75rem">(${backend})</span></label></div>` +
    fields.map(f => {
      const v = voiceData[f.key] || '';
      const lbl = typeof f.label === 'function' ? f.label() : f.label;
      const ph = f.placeholder ? ` placeholder="${esc(f.placeholder)}"` : '';
      if (f.type === 'textarea') return `<div class="edit-field"><label>${lbl}</label><textarea id="${prefix}-${f.key}" rows="2"${ph}>${esc(v)}</textarea></div>`;
      return `<div class="edit-field"><label>${lbl}</label><input id="${prefix}-${f.key}" value="${esc(v)}"${ph}></div>`;
    }).join('');
}

/** 从表单收集 TTS voice 参数 */
function _collectVoiceConfig(prefix) {
  const backend = _cache.get('sysconfig')?.data?.models?.tts_backend || 'mimo-voicedesign';
  const fields = TTS_VOICE_FIELDS[backend] || TTS_VOICE_FIELDS['mimo-voicedesign'];
  const voice = {};
  for (const f of fields) {
    const val = $val(`${prefix}-${f.key}`);
    if (val) voice[f.key] = val;
  }
  return Object.keys(voice).length ? voice : null;
}

function newChar() {
  _getTtsBackend().then(() => {
    _newEntityPanel('characters', {
      titleKey: 'char.title', reload: loadCharacters,
      buildExtra() { return { voice: _collectVoiceConfig('nc'), outfits: $val('nc-outfits') ? { default: $val('nc-outfits') } : null }; },
      extraHtml: _ttsVoiceFieldsHtml('nc'),
      fields: [
        { key: 'name', label: t('char.name') },
        { key: 'gender', label: t('char.gender'), type: 'select', options: [{ value: '', label: '-' }, { value: 'male', label: t('char.gender.male') }, { value: 'female', label: t('char.gender.female') }] },
        { key: 'appearance', label: t('char.appearance'), type: 'textarea' },
        { key: 'personality', label: t('char.personality') || '性格', type: 'textarea' },
        { key: 'outfits', label: t('char.outfit_desc'), type: 'textarea', getValue: true },
      ],
    });
  });
}
async function saveNewChar() { /* handled by _newEntityPanel */ }
function deleteChar(id) { deleteCharWithRef(id); }

async function editChar(id) {
  await _getTtsBackend();
  _editEntityPanel('characters', id, {
    titleKey: 'char.edit_title', notFoundKey: 'char.not_found', imgPrefix: 'ec', imgLabel: t('char.upload_img'), confirmMsg: '删除定妆照？',
    reload: loadCharacters,
    deleteFn: deleteCharWithRef,
    buildExtra() { return { voice: _collectVoiceConfig('ec'), outfits: $val('ec-outfits') ? { default: $val('ec-outfits') } : null }; },
    extraHtml: (item) => _ttsVoiceFieldsHtml('ec', item.voice || {}),
    fields: [
      { key: 'name', label: t('char.name') },
      { key: 'gender', label: t('char.gender'), type: 'select', options: [{ value: '', label: '-' }, { value: 'male', label: t('char.gender.male') }, { value: 'female', label: t('char.gender.female') }] },
      { key: 'appearance', label: t('char.appearance'), type: 'textarea' },
      { key: 'personality', label: t('char.personality') || '性格', type: 'textarea', getValue: c => c.personality || '' },
      { key: 'outfits', label: t('char.outfit_desc'), type: 'textarea', getValue: c => c.outfits?.default || '' },
    ],
  });
}

/** 通用图片上传 */
async function _uploadImg(entityType, id) {
  const prefix = entityType === 'characters' ? 'ec' : 'es';
  const fileInput = document.getElementById(`${prefix}-file`);
  if (!fileInput?.files?.[0]) return;
  const wrap = document.getElementById(`${prefix}-img-wrap`);
  _html(wrap, `<span class="dim">${t('common.uploading')}</span>`);
  const form = new FormData(); form.append('file', fileInput.files[0]);
  try {
    const r = await fetch(`${API}/assets/${entityType}/${id}/upload`, { method: 'POST', body: form });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || '上传失败');
    _html(wrap, `<div class="upload-preview"><img src="${d.url}"><button class="btn btn-xs btn-danger upload-remove" onclick="${prefix}RemoveImg('${id}')">✕</button></div>`);
    invalidateCache(entityType); toast('✅ 图片已上传');
    // 重新加载列表以刷新卡片缩略图
    if (entityType === 'characters' && typeof loadCharacters === 'function') loadCharacters();
    else if (entityType === 'scenes' && typeof loadScenes === 'function') loadScenes();
  } catch (e) { _html(wrap, `<span style="color:var(--red)">❌ ${e.message}</span>`); toast(e.message, 'error'); }
}

/** 通用拖拽上传 */
function _handleImgDrop(e, entityType, id) {
  e.preventDefault(); e.currentTarget.classList.remove('dragover');
  const file = e.dataTransfer?.files?.[0]; if (!file) return;
  const prefix = entityType === 'characters' ? 'ec' : 'es';
  const inp = document.getElementById(`${prefix}-file`);
  if (inp) { const dt = new DataTransfer(); dt.items.add(file); inp.files = dt.files; _uploadImg(entityType, id); }
}


// ══════════════════════════════════════════════════════════
// 场景管理
// ══════════════════════════════════════════════════════════


async function loadScenes() {
  _loadEntityPage('scenes', {
    pageId: 'page-scenes', icon: '🏔️', titleKey: 'scene.title',
    emptyHintKey: 'scene.empty_hint', emptyDescKey: 'scene.empty_desc',
    editFn: 'editScene', newFn: 'newScene', aiFn: 'showAIGenScene',
    card: s => {
      const thumb = (s.reference_images?.length) ? `<img src="${esc(s.reference_images[0])}" loading="lazy">` : '🏔️';
      return `<div class="entity-card" onclick="editScene('${esc(s.id)}')"><div class="entity-card-thumb">${thumb}</div><div class="entity-card-body"><h3>${esc(s.name || s.id)}</h3><p>${esc(s.description || '')}</p></div><div class="entity-card-footer"><span class="entity-card-id">${esc(s.id)}</span><span class="dim" style="font-size:.7rem">${esc(s.lighting || '')} <button class="btn btn-xs btn-danger" onclick="event.stopPropagation();deleteScene('${esc(s.id)}')" title="${t('btn.delete')}">🗑️</button></span></div></div>`;
    }
  });
}
function newScene() {
  _newEntityPanel('scenes', {
    titleKey: 'scene.title', reload: loadScenes,
    fields: [
      { key: 'name', label: t('scene.name') },
      { key: 'description', label: t('scene.desc'), type: 'textarea' },
      { key: 'lighting', label: t('scene.lighting') },
    ],
  });
}
function deleteScene(id) { deleteSceneWithRef(id); }

async function editScene(id) {
  _editEntityPanel('scenes', id, {
    titleKey: 'scene.edit_title', notFoundKey: 'scene.not_found', imgPrefix: 'es', imgLabel: t('scene.upload_img'), confirmMsg: '删除参考图？',
    reload: loadScenes,
    deleteFn: deleteSceneWithRef,
    fields: [
      { key: 'name', label: t('scene.name') },
      { key: 'description', label: t('scene.desc'), type: 'textarea' },
      { key: 'lighting', label: t('scene.lighting') },
    ],
  });
}

// ── DOM 取值快捷 ──
function $val(id) { return document.getElementById(id)?.value || ''; }

// ══════════════════════════════════════════════════════════
// 分镜表
// ══════════════════════════════════════════════════════════

const SB_FIELDS = ['scene', 'characters', 'action', 'dialogue', 'camera', 'shot_type', 'duration', 'emotion', 'language'];
let _sbViewMode = localStorage.getItem('sb_view') || 'table'; // 'table' | 'timeline'

function _sbViewToggle() {
  return `<div class="view-toggle">
    <button class="btn btn-xs ${_sbViewMode==='table'?'active':''}" onclick="setSBView('table')">📋 表格</button>
    <button class="btn btn-xs ${_sbViewMode==='timeline'?'active':''}" onclick="setSBView('timeline')">📐 ${t('sb.timeline')}</button>
  </div>`;
}

function setSBView(mode) {
  _sbViewMode = mode;
  localStorage.setItem('sb_view', mode);
  loadStoryboard();
}

// ══════════════════════════════════════════════════════════
// AI 生成
// ══════════════════════════════════════════════════════════

// ── AI 生成通用执行器 ──

async function _runAIGen(apiPath, body, statusId, overlayId, label, cacheKey, reloadFn) {
  const statusEl = document.getElementById(statusId);
  const reset = _btnLoad(document.querySelector(`#${overlayId} .btn-primary`), '⏳ 生成中...');
  _html(statusEl, `⏳ ${label}...`);
  try {
    const { task_id } = await api(apiPath, { method: 'POST', body });
    const result = await pollTask(task_id, info => _html(statusEl, `⏳ ${info.message || 'AI 生成中...'} (${info.progress || 0}%)`));
    if (result.status === 'success' && result.result?.status === 'done') {
      const r = result.result;
      const countLabel = r.count !== undefined ? `生成 ${r.count} 个` : '完成';
      _html(statusEl, `✅ ${countLabel}`);
      toast(`✅ 已${countLabel}`);
      invalidateCache(cacheKey);
      setTimeout(() => { document.getElementById(overlayId)?.remove(); reloadFn(); }, 1500);
    } else {
      const err = result.result?.reason || result.error || '生成失败';
      _html(statusEl, `❌ ${err}`); toast(`❌ ${err}`, 'error');
    }
  } catch (e) { _html(statusEl, `❌ ${e.message}`); toast(`❌ ${e.message}`, 'error'); }
  reset();
}

function showAIGenStoryboard() {
  _showOverlay('ai-gen-sb-overlay', '🤖 AI 生成分镜表', `
    <div class="edit-field"><label>剧情大纲</label>
      <textarea id="ai-sb-outline" rows="8" placeholder="输入剧情大纲，例如：\n\n林夏独自在家等顾辰来给她过生日，等了很久他都没回消息，她很失落。顾辰骑车赶路，终于到了。开门后两人对视，顾辰送上花，林夏感动落泪。"></textarea></div>
    <div class="edit-field-row">
      <div class="edit-field"><label>集数</label><input id="ai-sb-ep" type="number" value="${ep}" min="1"></div>
      <div class="edit-field"><label>目标时长(秒)</label><input id="ai-sb-dur" type="number" value="90" min="10" max="600"></div>
    </div>
    <div class="edit-field"><label><input type="checkbox" id="ai-sb-append"> 追加到现有分镜表（不覆盖）</label></div>
    <div id="ai-sb-status" class="dim" style="margin-top:0.5rem"></div>`, `doAIGenStoryboard()`, '🚀 生成');
}

async function doAIGenStoryboard() {
  const outline = document.getElementById('ai-sb-outline')?.value?.trim();
  if (!outline || outline.length < 10) { toast('请输入至少 10 字的剧情大纲', 'error'); return; }
  const episode = parseInt(document.getElementById('ai-sb-ep')?.value) || ep;
  const duration = parseInt(document.getElementById('ai-sb-dur')?.value) || 90;
  const append = document.getElementById('ai-sb-append')?.checked || false;
  await _runAIGen('/llm/storyboard', { episode, outline, duration, append },
    'ai-sb-status', 'ai-gen-sb-overlay', 'AI 生成分镜',
    `storyboard/${episode}`, () => {
      ep = episode;
      const p = document.querySelector('.page.active');
      if (p?.id === 'page-storyboard') loadStoryboard();
      else if (p?.id === 'page-pipeline') loadPipeline();
    });
}

function showAIGenCharacter() {
  _showOverlay('ai-gen-char-overlay', '🤖 AI 生成角色', `
    <div class="edit-field"><label>角色描述（每行一个角色）</label>
      <textarea id="ai-char-desc" rows="6" placeholder="输入角色描述，例如：\n\n22岁温柔女生，长发，喜欢穿浅色衣服，说话轻声细语\n25岁帅气男生，短发阳光，运动型，性格开朗"></textarea></div>
    <div id="ai-char-status" class="dim" style="margin-top:0.5rem"></div>`, `doAIGenCharacter()`, '🚀 生成');
}

async function doAIGenCharacter() {
  const descText = document.getElementById('ai-char-desc')?.value?.trim();
  if (!descText) { toast('请输入角色描述', 'error'); return; }
  const descriptions = descText.split('\n').map(s => s.trim()).filter(s => s.length > 0);
  if (!descriptions.length) { toast('请输入至少一个角色描述', 'error'); return; }
  await _runAIGen('/llm/characters', { descriptions }, 'ai-char-status', 'ai-gen-char-overlay',
    `正在生成 ${descriptions.length} 个角色`, 'characters', loadCharacters);
}

function showAIGenScene() {
  _showOverlay('ai-gen-scene-overlay', '🤖 AI 生成场景', `
    <div class="edit-field"><label>场景描述（每行一个场景）</label>
      <textarea id="ai-scene-desc" rows="6" placeholder="输入场景描述，例如：\n\n现代简约客厅，米色沙发，落地窗暖光\n繁华商业街，霓虹灯闪烁，人来人往"></textarea></div>
    <div id="ai-scene-status" class="dim" style="margin-top:0.5rem"></div>`, `doAIGenScene()`, '🚀 生成');
}

async function doAIGenScene() {
  const descText = document.getElementById('ai-scene-desc')?.value?.trim();
  if (!descText) { toast('请输入场景描述', 'error'); return; }
  const descriptions = descText.split('\n').map(s => s.trim()).filter(s => s.length > 0);
  if (!descriptions.length) { toast('请输入至少一个场景描述', 'error'); return; }
  await _runAIGen('/llm/scenes', { descriptions }, 'ai-scene-status', 'ai-gen-scene-overlay',
    `正在生成 ${descriptions.length} 个场景`, 'scenes', loadScenes);
}

async function loadStoryboard() {
  const el = document.getElementById('page-storyboard');
  try {
    const episodes = await loadEpisodeSelector();
    const d = await cachedFetch(`storyboard/${ep}`, () => api(`/storyboard/${ep}`));
    const ss = d.shots || [];
    const epSelector = _episodeSelectHtml(episodes, 'switchEpisode');
    const header = `<div class="card"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem"><h2>${t('sb.title')}</h2>
      <div style="display:flex;gap:0.5rem;align-items:center;flex-wrap:wrap">${epSelector}${_sbViewToggle()}<button class="btn btn-outline btn-ai" onclick="showAIGenStoryboard()">🤖 AI 生成分镜</button><button class="btn btn-outline" onclick="exportStoryboard()">📤 ${t('sb.export')}</button><button class="btn btn-outline" onclick="showImportDialog()">📥 ${t('sb.import')}</button><button class="btn btn-primary" onclick="navTo('pipeline')">🎬 ${t('nav.pipeline')}</button><button class="btn btn-success" onclick="addShot()">+ ${t('btn.add')}</button></div></div>
      <p class="dim" style="font-size:.76rem;margin-bottom:.5rem">${t('sb.drag_hint')}</p>`;

    if (!ss.length) {
      el.innerHTML = header + `<div class="empty-state"><div class="empty-state-icon">📝</div><h3>${t('sb.none')}</h3><p>${t('sb.empty_desc')}</p><button class="btn btn-ai" onclick="showAIGenStoryboard()">🤖 AI 生成分镜</button></div></div>`;
      return;
    }

    if (_sbViewMode === 'timeline') {
      // 时间轴视图
      const timeline = `<div class="timeline-container">${ss.map((s, i) => {
        const sid = _shotId(s, i);
        return `<div class="timeline-item" id="tl-${esc(sid)}"><div class="timeline-dot"></div>
          <div class="timeline-card">
            <div class="timeline-thumb" id="tl-thumb-${esc(sid)}"><div class="thumb-skeleton"><div class="thumb-skeleton-pulse"></div></div></div>
            <div class="timeline-info">
              <div class="timeline-info-head"><span class="timeline-sid">${esc(sid)}</span><span class="timeline-meta">${esc(s.scene || '')} · ${esc(s.characters || '')}</span></div>
              <div class="timeline-info-body">${esc((s.action || '').substring(0, 60))}${(s.action||'').length > 60 ? '...' : ''}</div>
              ${s.dialogue && s.dialogue !== '......' ? `<div class="timeline-info-dialogue">"${esc((s.dialogue || '').substring(0, 50))}"</div>` : ''}
              <div class="timeline-meta" style="margin-top:.25rem">${esc(s.camera || '')} · ${esc(s.shot_type || '')} · ${s.duration || 4}s · ${esc(s.emotion || 'neutral')} · ${LANGUAGES.find(l => l.value === (s.language || 'zh'))?.label || s.language || 'zh'}</div>
              <div class="timeline-actions">${_actionBtns(i)}</div>
            </div>
          </div></div>`;
      }).join('')}</div>`;
      el.innerHTML = header + timeline + '</div>';
      // 加载缩略图
      ss.forEach((_, i) => _loadTimelineThumb(i));
      _initTimelineSortable();
    } else {
      // 表格视图
      const rows = ss.map((s, i) => `<tr>
        <td><span class="drag-handle" title="拖拽排序">⠿</span></td>
        <td>${_shotId(s, i)}</td>
        ${SB_FIELDS.slice(0, 4).map(f => `<td><input class="sb-inline-input" value="${esc(s[f] || '')}" data-idx="${i}" data-field="${f}" onchange="updateShotField(this)"></td>`).join('')}
        <td><select class="sb-inline-input" data-idx="${i}" data-field="camera" onchange="updateShotField(this)">${_selectOpts(_cameras(), s.camera)}</select></td>
        <td><select class="sb-inline-input" data-idx="${i}" data-field="shot_type" onchange="updateShotField(this)">${_selectOpts(_shotTypes(), s.shot_type)}</select></td>
        <td><input class="sb-inline-input" type="number" value="${s.duration || 4}" min="1" max="30" data-idx="${i}" data-field="duration" onchange="updateShotField(this)"></td>
        <td><select class="sb-inline-input" data-idx="${i}" data-field="emotion" onchange="updateShotField(this)">${_selectOpts(EMOTIONS, s.emotion)}</select></td>
        <td><select class="sb-inline-input" data-idx="${i}" data-field="language" onchange="updateShotField(this)">${LANGUAGES.map(l => `<option value="${l.value}" ${(s.language || 'zh') === l.value ? 'selected' : ''}>${l.label}</option>`).join('')}</select></td>
        <td><button class="btn btn-xs btn-danger" onclick="deleteShotFromSB(${i})">🗑️</button></td></tr>`).join('');
      el.innerHTML = header + `<div style="overflow-x:auto"><table><thead><tr><th></th><th>${t('sb.shot_id')}</th><th>${t('edit.scene')}</th><th>${t('edit.characters')}</th><th>${t('edit.action')}</th><th>${t('edit.dialogue')}</th><th>${t('edit.camera')}</th><th>${t('edit.shot_type')}</th><th>${t('edit.duration')}</th><th>${t('sb.emotion')}</th><th>${t('edit.language')}</th><th></th></tr></thead>
      <tbody>${rows}</tbody></table></div></div>`;
      _initSortable();
    }
  } catch (e) { el.innerHTML = `<div class="card"><h2>${t('common.error')}</h2><p>${esc(e.message)}</p></div>`; }
}

async function _loadTimelineThumb(idx) {
  const sid = _shotId(shots[idx], idx);
  const el = document.getElementById(`tl-thumb-${sid}`);
  if (!el) return;
  try {
    const r = (await cachedFetch(`res/${ep}/${sid}`, () => api(`/shots/${ep}/${sid}/resources`))).resources || {};
    const item = document.getElementById(`tl-${sid}`);
    if (r.frame) {
      el.innerHTML = `<img src="/api/files/${ep}/${sid}/frame.png" loading="lazy" onclick="previewRes('${sid}','frame')" style="cursor:pointer" title="点击放大">`;
      if (item) item.classList.add('has-frame');
    } else {
      el.innerHTML = '🎬';
    }
    if (r.video && item) item.classList.add('has-video');
    if (r.synced && item) item.classList.add('has-synced');
  } catch { el.innerHTML = '🎬'; }
}

let _sbDirty = false, _sbSaving = false;
const _debouncedSaveSB = debounce(async () => {
  if (!_sbDirty || _sbSaving) return;
  _sbSaving = true;
  try {
    // 直接从 DOM 同步到内存中的 shots，避免 GET→POST 竞态
    document.querySelectorAll('.sb-inline-input').forEach(inp => {
      const i = parseInt(inp.dataset.idx);
      if (shots[i]) shots[i][inp.dataset.field] = inp.value;
    });
    await api(`/storyboard/${ep}`, { method: 'POST', body: { shots } });
    invalidateCache(`storyboard/${ep}`);
    _sbDirty = false;
    toast(t('toast.saved'));
  } catch (e) { toast(e.message, 'error'); }
  finally { _sbSaving = false; }
}, 1000);
function updateShotField() {
  if (!_sbDirty) pushUndo(t('sb.title')); // 首次修改时保存快照用于 undo
  _sbDirty = true;
  _debouncedSaveSB();
}

async function deleteShotFromSB(idx) {
  const sid = shots[idx]?.shot_id || idx + 1;
  if (!await modalConfirm(t('confirm.delete_shot', { id: sid }))) return;
  pushUndo(`${t('btn.delete')} ${sid}`);
  shots.splice(idx, 1);
  try { await api(`/storyboard/${ep}`, { method: 'POST', body: { shots } }); invalidateCache(`storyboard/${ep}`); toast(t('toast.deleted')); loadStoryboard(); } catch (e) { toast(e.message, 'error'); }
}

async function addShot() {
  const maxNum = Math.max(0, ...shots.map(s => parseInt(s.shot_id, 10)).filter(n => !isNaN(n)));
  const newId = String(maxNum + 1).padStart(3, '0');
  pushUndo(`${t('btn.add')} ${newId}`);
  const newShot = { episode: ep, shot_id: newId, scene: '', characters: '', action: '', dialogue: '', camera: _cameras()[0], shot_type: _shotTypes()[2], duration: 4, emotion: 'neutral', language: 'zh', outfit: '', action_en: '', dialogue_en: '' };
  shots.push(newShot);
  try { await api(`/storyboard/${ep}`, { method: 'POST', body: { shots } }); invalidateCache(`storyboard/${ep}`); toast(t('toast.created')); loadStoryboard(); } catch (e) { toast(e.message, 'error'); }
}

// ══════════════════════════════════════════════════════════
// Seko 影视策划案
// ══════════════════════════════════════════════════════════

const _sekoTasks = [];  // { task_id, prompt, status, created, result }

async function loadSeko() {
  const el = document.getElementById('page-seko');
  // 检查 API Key
  let sekoAvailable = false;
  try {
    const tools = await api('/tools');
    sekoAvailable = tools.tools?.seko?.available || false;
  } catch {}

  const taskRows = _sekoTasks.length ? _sekoTasks.map((task, i) => `
    <div class="card" style="margin-bottom:.5rem" id="seko-task-${i}">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.5rem">
        <div>
          <span class="dim" style="font-size:.8rem">${task.task_id}</span>
          <span style="margin-left:.5rem">${esc(task.prompt.slice(0, 60))}${task.prompt.length > 60 ? '...' : ''}</span>
        </div>
        <div style="display:flex;gap:.3rem;align-items:center">
          <span class="status-dot ${task.status === 'OK' ? 'ok' : task.status === 'FAIL' ? 'err' : ''}"></span>
          <span>${t('seko.status_' + (task.status || 'RUNNING'))}</span>
          <button class="btn btn-xs btn-outline" onclick="sekoCheckStatus(${i})">${t('seko.check_btn')}</button>
          ${task.status === 'OK' ? `<button class="btn btn-xs btn-outline" onclick="sekoDownload(${i})">${t('seko.download_btn')}</button>` : ''}
          ${task.status === 'OK' ? `<button class="btn btn-xs btn-primary" onclick="sekoImport(${i})">${t('seko.import_btn') || '📥 导入项目'}</button>` : ''}
          <button class="btn btn-xs btn-outline" onclick="sekoModify(${i})">${t('seko.modify_btn')}</button>
        </div>
      </div>
      ${task.result ? `<details style="margin-top:.5rem"><summary>${t('seko.result_title')}</summary><pre style="max-height:400px;overflow:auto;font-size:.8rem;background:var(--bg3,#1a1e2e);color:var(--fg,#e6e8ef);padding:.5rem;border-radius:4px;border:1px solid rgba(255,255,255,.06)">${esc(JSON.stringify(task.result, null, 2))}</pre></details>` : ''}
    </div>
  `).join('') : `<div class="card"><p style="color:var(--text-dim,#888)">${t('seko.no_tasks')}</p></div>`;

  el.innerHTML = `
    <div class="card">
      <h2>${t('seko.title')}</h2>
      <p class="dim">${t('seko.desc')}</p>
      ${!sekoAvailable ? `<div style="background:#fef3cd;color:#856404;padding:.8rem;border-radius:6px;margin-top:.5rem">${t('seko.api_key_unset')}</div>` : ''}
    </div>
    <div class="card">
      <h3>${t('seko.new_proposal')}</h3>
      <div class="form-row"><label>${t('seko.prompt_label')}</label>
        <textarea id="seko-prompt" rows="4" style="width:100%" placeholder="${t('seko.prompt_ph')}" ${!sekoAvailable ? 'disabled' : ''}></textarea></div>
      <button class="btn btn-primary" onclick="sekoSubmit()" id="seko-submit-btn" ${!sekoAvailable ? 'disabled' : ''}>${t('seko.submit_btn')}</button>
      <span id="seko-submit-msg" class="dim" style="margin-left:.5rem"></span>
    </div>
    <div class="card">
      <h3>${t('seko.task_list')}</h3>
      ${taskRows}
    </div>`;
}

async function sekoSubmit() {
  const prompt = document.getElementById('seko-prompt')?.value?.trim();
  if (!prompt) return;
  const btn = document.getElementById('seko-submit-btn');
  const msg = document.getElementById('seko-submit-msg');
  btn.disabled = true; btn.textContent = t('seko.submitting');
  try {
    const r = await api('/seko/proposal', { method: 'POST', body: { prompt } });
    _sekoTasks.unshift({ task_id: r.task_id, prompt, status: 'RUNNING', created: new Date().toLocaleString(), result: null });
    msg.innerHTML = `<span style="color:#22c55e">${t('seko.submitted', { id: r.task_id })}</span>`;
    loadSeko();
  } catch (e) {
    msg.innerHTML = `<span style="color:#ef4444">${t('seko.submit_fail')}: ${esc(e.message)}</span>`;
  } finally {
    btn.disabled = false; btn.textContent = t('seko.submit_btn');
  }
}

async function sekoCheckStatus(idx) {
  const task = _sekoTasks[idx];
  if (!task) return;
  task.status = 'RUNNING';
  loadSeko();
  try {
    const r = await api('/seko/proposal/status', { method: 'POST', body: { task_id: task.task_id } });
    task.status = r.status || 'UNKNOWN';
    task.result = r.raw?.data?.result || r.raw?.data || null;
    if (task.status === 'OK') toast(t('toast.task_done'));
    else if (task.status === 'FAIL') toast(t('toast.task_fail'), 'error');
    loadSeko();
  } catch (e) {
    task.status = 'FAIL';
    toast(e.message, 'error');
    loadSeko();
  }
}

async function sekoDownload(idx) {
  const task = _sekoTasks[idx];
  if (!task) return;
  try {
    const r = await api('/seko/proposal/status', {
      method: 'POST',
      body: { task_id: task.task_id, download_dir: '__project_assets__' }
    });
    const count = r.downloaded?.length || 0;
    toast(t('seko.downloaded', { n: count }));
  } catch (e) { toast(e.message, 'error'); }
}

async function sekoModify(idx) {
  const task = _sekoTasks[idx];
  if (!task) return;
  const prompt = await modalPrompt(t('seko.modify_ph'), '', { type: 'textarea', placeholder: t('seko.modify_ph') });
  if (!prompt) return;
  try {
    const r = await api('/seko/proposal/modify', { method: 'POST', body: { task_id: task.task_id, prompt } });
    _sekoTasks.unshift({ task_id: r.task_id, prompt: `[修改] ${prompt}`, status: 'RUNNING', created: new Date().toLocaleString(), result: null });
    toast(t('seko.task_added'));
    loadSeko();
  } catch (e) { toast(e.message, 'error'); }
}

async function sekoImport(idx) {
  const task = _sekoTasks[idx];
  if (!task?.result) return;

  // 从策划案中提取标题作为默认项目名
  const outlineStep = task.result.steps?.find(s => s.step === 'outline');
  const outlineText = outlineStep?.stepOutput || task.prompt || '';
  const titleMatch = outlineText.match(/剧[本名][：:]\s*(.+)/);
  const defaultName = titleMatch ? titleMatch[1].trim().slice(0, 30) : '';

  // 选择导入方式
  const importMode = await modalPrompt(
    (t('seko.import_mode_title') || '导入方式') + '\n\n' +
    (t('seko.import_mode_desc') || '输入新项目名创建项目并导入，留空则导入到当前项目'),
    defaultName,
    { type: 'text', placeholder: t('seko.import_mode_ph') || '留空 = 导入当前项目' }
  );
  if (importMode === null) return; // 取消

  const projectName = importMode.trim();

  // 防重入：禁用按钮
  const btn = document.querySelector(`#seko-task-${idx} .btn-primary`);
  if (btn) { btn.disabled = true; btn.textContent = '⏳ 导入中...'; }
  try {
    toast(projectName
      ? (t('seko.import_creating') || '正在创建项目并导入...')
      : (t('seko.import_submitting') || '正在提交导入任务...'));
    const r = await api('/seko/proposal/import', {
      method: 'POST',
      body: {
        proposal_data: task.result,
        episode: 1,
        import_characters: true,
        import_scenes: true,
        import_storyboard: true,
        download_images: true,
        project_name: projectName,
      }
    });
    const taskId = r.task_id;
    toast((t('seko.import_submitted') || '导入任务已提交') + ` (${taskId})`);
    await _pollSekoImportTask(taskId, projectName);
  } catch (e) {
    toast((t('seko.import_fail') || '导入失败') + `: ${e.message}`, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = t('seko.import_btn') || '📥 导入项目'; }
  }
}

async function _pollSekoImportTask(taskId, projectName) {
  const maxWait = 960; // 最长等 16 分钟（对齐 Celery soft_time_limit 900s + 余量）
  const interval = 3;
  let waited = 0;
  while (waited < maxWait) {
    await new Promise(r => setTimeout(r, interval * 1000));
    waited += interval;
    try {
      const info = await api(`/tasks/${taskId}`);
      if (info.status === 'success') {
        const res = info.result || {};
        const msg = [
          res.characters ? `角色 ${res.characters}` : '',
          res.scenes ? `场景 ${res.scenes}` : '',
          res.shots ? `分镜 ${res.shots}` : '',
          res.images_downloaded ? `图片 ${res.images_downloaded}` : '',
        ].filter(Boolean).join('、');
        let doneMsg = (t('seko.import_done') || '导入完成！') + (msg ? ` (${msg})` : '');
        if (projectName) {
          doneMsg += ` | ${t('seko.import_switch_hint') || '已创建项目'}: ${projectName}`;
          // 刷新项目列表
          try { loadProjects(); } catch {}
        }
        toast(doneMsg);
        return;
      } else if (info.status === 'failed') {
        toast((t('seko.import_fail') || '导入失败') + `: ${info.error || ''}`, 'error');
        return;
      }
      // running → 继续等
    } catch {
      // 网络抖动，继续等
    }
  }
  toast(t('seko.import_timeout') || '导入任务超时，请稍后查看结果');
}

// ══════════════════════════════════════════════════════════
// 项目管理
// ══════════════════════════════════════════════════════════

async function loadProjects() {
  const el = document.getElementById('page-projects');
  el.innerHTML = `<div class="card"><h2>${t('common.loading')}</h2></div>`;
  try {
    const d = await api('/projects');
    const rows = (d.projects || []).map(p => {
      const switchBtn = p.active ? '' : `<button class="btn btn-sm btn-primary" onclick="switchProj('${esc(p.name)}')">${t('common.switch')}</button> `;
      const deleteBtn = (!p.active && !p.isDefault) ? `<button class="btn btn-sm btn-danger" onclick="deleteProj('${esc(p.name)}')">🗑️</button>` : '';
      return `<tr><td>${p.active ? '→' : ''}</td><td>${esc(p.name)}</td><td class="dim" style="font-size:0.75rem">${esc(p.path)}</td><td>${p.active ? `<span class="badge badge-green">${t('common.current')}</span>` : switchBtn + deleteBtn}</td></tr>`;
    }).join('');
    el.innerHTML = `<div class="card"><div style="display:flex;justify-content:space-between;margin-bottom:1rem"><h2>${t('proj.title')}</h2><button class="btn btn-success" onclick="newProj()">+ ${t('btn.add')}</button></div>
      <table><thead><tr><th></th><th>${t('common.name')}</th><th>${t('common.path')}</th><th>${t('common.status')}</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div id="ep-manager"></div>`;
    loadEpisodeManager();
  } catch (e) { el.innerHTML = `<div class="card"><h2>${t('common.error')}</h2><p>${esc(e.message)}</p></div>`; }
}
async function newProj() { const n = await modalPrompt(t('proj.input_name')); if (!n) return; api('/projects/new', { method: 'POST', body: { name: n } }).then(() => { toast(t('toast.created')); loadProjects(); }).catch(e => toast(e.message, 'error')); }
function switchProj(name) {
  api('/projects/switch', { method: 'POST', body: { name } }).then(() => {
    _cache.clear();
    _undoStack.length = 0;
    _redoStack.length = 0;
    ep = 1;
    toast(t('toast.switched'));
    loadProjects();
    const p = document.querySelector('.page.active');
    if (p) { const pageName = p.id.replace('page-', ''); if (PAGES[pageName]) PAGES[pageName](); }
  }).catch(e => toast(e.message, 'error'));
}
async function deleteProj(n) {
  if (!await modalConfirm(t('proj.confirm_delete', { name: n }))) return;
  api(`/projects/${encodeURIComponent(n)}`, { method: 'DELETE' }).then(() => {
    _cache.clear();
    toast(t('proj.deleted'));
    loadProjects();
  }).catch(e => toast(e.message, 'error'));
}

// ══════════════════════════════════════════════════════════
// 系统设置
// ══════════════════════════════════════════════════════════

function _backendSection(label, icon, idPrefix, backends, backend, url, available, reason, opts = {}) {
  const toolName = idPrefix === 'lipsync' ? 'lipsync' : idPrefix;
  const apiKeyHtml = opts.showApiKey ? `<div class="form-row"><label>${t('set.tts_api_key')}</label><div style="display:flex;gap:.3rem;flex:1"><input id="cfg-${idPrefix}-key" type="password" value="${esc(opts.apiKey || '')}" style="flex:1" placeholder="MIMO_API_KEY"><button class="btn btn-xs btn-outline" onclick="_toggleKeyVis('cfg-${idPrefix}-key','cfg-${idPrefix}-key-toggle')" id="cfg-${idPrefix}-key-toggle">👁</button></div></div>` : '';
  const testHtml = opts.showTest ? `<div style="margin-top:.5rem"><div class="form-row"><label>${t('set.tts_test_text')}</label><input id="cfg-${idPrefix}-test-text" value="${esc(opts.testText || '你好，这是一段测试语音。')}" style="flex:1"></div>
    <button class="btn btn-xs btn-outline" onclick="testTtsPreview()" id="test-btn-tts-preview" style="margin-top:.3rem">🎤 ${t('set.tts_test')}</button>
    <span id="test-result-tts-preview" class="dim" style="font-size:0.8rem;margin-left:0.3rem"></span></div>` : '';
  return `<div class="config-section"><h3>${icon} ${label}</h3>
    <div class="form-row"><label>${t('set.backend')}</label><select id="cfg-${idPrefix}" onchange="_updateUrl('${idPrefix}')">${backends.map(b => `<option value="${b}" ${backend === b ? 'selected' : ''}>${b}</option>`).join('')}</select></div>
    <div class="form-row"><label>${t('set.address')}</label><input id="cfg-${idPrefix}-url" value="${esc(url)}"></div>
    ${apiKeyHtml}
    <div class="tool-status-inline"><span class="status-dot ${available ? 'ok' : 'err'}"></span>${available ? t('dash.available') : reason || t('dash.unavailable')}
      <button class="btn btn-xs btn-outline" onclick="testTool('${toolName}')" id="test-btn-${toolName}">🔌 ${t('set.test')}</button>
      <span id="test-result-${toolName}" class="dim" style="font-size:0.8rem;margin-left:0.3rem"></span></div>
    ${testHtml}</div>`;
}

function _updateUrl(prefix) {
  const key = $val(`cfg-${prefix}`).replace(/-/g, '_');
  const cfg = _cache.get('sysconfig')?.data || {};
  const inp = document.getElementById(`cfg-${prefix}-url`);
  if (inp) inp.value = cfg.models?.[key]?.api_url || '';
  // 同步 API Key 字段
  const keyInp = document.getElementById(`cfg-${prefix}-key`);
  if (keyInp) keyInp.value = cfg.models?.[key]?.api_key || '';
}

function _resolveBackendUrl(cfg, prefix) {
  const backend = cfg.models?.[`${prefix}_backend`] || '';
  return { backend, url: cfg.models?.[backend.replace(/-/g, '_')]?.api_url || '' };
}

async function loadSettings() {
  const el = document.getElementById('page-settings');
  try {
    const [sysCfg, env, td] = await Promise.all([api('/system/config'), api('/system/env'), api('/tools')]);
    _cache.set('sysconfig', { data: sysCfg, ts: Date.now() });
    const tools = td.tools || {}, lang = localStorage.getItem('drama_lang') || 'zh';
    const tts = _resolveBackendUrl(sysCfg, 'tts'), ls = _resolveBackendUrl(sysCfg, 'lip_sync');
    const llm = sysCfg.llm || {};
    const training = sysCfg.training || {};
    el.innerHTML = `
      <div class="card"><h2>🌐 语言 / Language</h2><div class="form-row"><label>Language</label>
        <select id="cfg-lang" onchange="setLang(this.value);loadSettings()"><option value="zh" ${lang === 'zh' ? 'selected' : ''}>中文</option><option value="en" ${lang === 'en' ? 'selected' : ''}>English</option></select></div></div>
      <div class="card"><h2>💻 ${t('set.env')}</h2><div class="info-grid"><div><span class="dim">${t('set.os')}:</span> ${env.os}</div><div><span class="dim">${t('set.python')}:</span> ${env.python}</div></div></div>
      <div class="card"><h2>${t('set.presets')}</h2>
        <div class="preset-btns">
          <button class="preset-btn" onclick="applyPreset('local_comfyui')">${t('set.preset_local')}</button>
          <button class="preset-btn" onclick="applyPreset('cloud_siliconflow')">${t('set.preset_cloud')}</button>
          <button class="preset-btn" onclick="applyPreset('ollama_local')">${t('set.preset_ollama')}</button>
        </div>
      </div>
      <div class="card"><h2>🔧 系统配置</h2>
        ${_backendSection(t('set.tts'), '🎤', 'tts', ['mimo-voicedesign', 'mimo-voiceclone', 'gpt-sovits', 'cosyvoice', 'fish-speech'], tts.backend, tts.url, tools.tts?.available, tools.tts?.reason, { showApiKey: true, apiKey: sysCfg.models?.[tts.backend.replace(/-/g, '_')]?.api_key || '', showTest: true })}
        ${_backendSection(t('set.lipsync'), '👄', 'lipsync', ['musetalk', 'sadtalker', 'wav2lip'], ls.backend, ls.url, tools.lipsync?.available, tools.lipsync?.reason)}
        <div class="config-section"><h3>🎨 ComfyUI</h3>
          <div class="form-row"><label>${t('set.address')}</label><input id="cfg-comfyui" value="${esc(sysCfg.comfyui?.url || '')}"></div>
          <div class="form-row"><label>API Key</label><input id="cfg-comfyui-key" value="${esc(sysCfg.comfyui?.api_key || '')}" placeholder="${t('set.optional')}"></div>
          <div class="tool-status-inline"><span class="status-dot ${tools.comfyui?.available ? 'ok' : 'err'}"></span>${tools.comfyui?.available ? t('dash.available') : tools.comfyui?.reason || t('dash.unavailable')}
            <button class="btn btn-xs btn-outline" onclick="testTool('comfyui')" id="test-btn-comfyui">🔌 ${t('set.test')}</button>
            <span id="test-result-comfyui" class="dim" style="font-size:0.8rem;margin-left:0.3rem"></span></div></div>
        <div class="config-section"><h3>🧠 ${t('set.llm')}</h3>
          <div class="form-row"><label>${t('set.llm_enabled')}</label><select id="cfg-llm-enabled"><option value="false" ${!llm.enabled ? 'selected' : ''}>${lang==='zh'?'关闭':'Off'}</option><option value="true" ${llm.enabled ? 'selected' : ''}>${lang==='zh'?'开启':'On'}</option></select></div>
          <div class="form-row"><label>${t('set.backend')}</label><select id="cfg-llm-backend"><option value="openai" ${llm.backend==='openai'?'selected':''}>OpenAI 兼容 (SiliconFlow / Zhipu / ...)</option><option value="ollama" ${llm.backend==='ollama'?'selected':''}>Ollama</option></select></div>
          <div class="form-row"><label>API URL</label><input id="cfg-llm-url" value="${esc(llm.base_url || '')}"></div>
          <div class="form-row"><label>${t('set.llm_model')}</label><input id="cfg-llm-model" value="${esc(llm.model || '')}"></div>
          <div class="form-row"><label>API Key</label><div style="display:flex;gap:.3rem;flex:1"><input id="cfg-llm-key" type="password" value="${esc(llm.api_key || '')}" style="flex:1"><button class="btn btn-xs btn-outline" onclick="_toggleKeyVis()" id="cfg-llm-key-toggle">👁</button></div></div>
          <div class="tool-status-inline"><span class="status-dot ${tools.llm?.available ? 'ok' : 'err'}"></span>${tools.llm?.available ? t('dash.available') : tools.llm?.reason || t('dash.unavailable')}
            <button class="btn btn-xs btn-outline" onclick="testTool('llm')" id="test-btn-llm">🔌 ${t('set.test')}</button>
            <span id="test-result-llm" class="dim" style="font-size:0.8rem;margin-left:0.3rem"></span></div></div>
        <div class="config-section"><h3>⚡ ${t('batch.concurrent')}</h3>
          <div class="form-row"><label>${t('batch.concurrent')}</label><select id="cfg-concurrency" onchange="localStorage.setItem('drama_concurrency',this.value)">
            <option value="1" ${(localStorage.getItem('drama_concurrency')||'1')==='1'?'selected':''}>1</option>
            <option value="2" ${localStorage.getItem('drama_concurrency')==='2'?'selected':''}>2</option>
            <option value="3" ${localStorage.getItem('drama_concurrency')==='3'?'selected':''}>3</option>
            <option value="5" ${localStorage.getItem('drama_concurrency')==='5'?'selected':''}>5</option>
          </select></div></div>
        <div class="config-section"><h3>🎬 Seko 影视策划</h3>
          <div class="form-row"><label>API Key</label><div style="display:flex;gap:.3rem;flex:1"><input id="cfg-seko-key" type="password" value="${esc(sysCfg.seko?.api_key || '')}" style="flex:1" placeholder="获取: seko.sensetime.com/explore"><button class="btn btn-xs btn-outline" onclick="_toggleKeyVis('cfg-seko-key','cfg-seko-key-toggle')" id="cfg-seko-key-toggle">👁</button></div></div>
          <div class="tool-status-inline"><span class="status-dot ${tools.seko?.available ? 'ok' : 'err'}"></span>${tools.seko?.available ? t('dash.available') : tools.seko?.reason || t('dash.unavailable')}</div></div>
        <div class="config-section"><h3>🏋️ ${t('set.training')}</h3>
          <div class="form-row"><label>${t('set.backend')}</label><select id="cfg-training-backend"><option value="fluxgym" selected>FluxGym</option></select></div>
          <div class="form-row"><label>${t('set.address')}</label><input id="cfg-training-url" value="${esc(training.api_url || '')}" placeholder="http://127.0.0.1:7860"></div>
          <div class="form-row"><label>${t('set.training_timeout')}</label><input id="cfg-training-timeout" type="number" value="${training.timeout || 3600}" min="60" max="86400"></div>
          <div class="form-row"><label>${t('set.training_poll')}</label><input id="cfg-training-poll" type="number" value="${training.poll_interval || 10}" min="5" max="120"></div>
          <div class="tool-status-inline"><span class="status-dot ${tools.training?.available ? 'ok' : 'err'}"></span>${tools.training?.available ? t('dash.available') : tools.training?.reason || t('dash.unavailable')}
            <button class="btn btn-xs btn-outline" onclick="testTool('training')" id="test-btn-training">🔌 ${t('set.test')}</button>
            <span id="test-result-training" class="dim" style="font-size:0.8rem;margin-left:0.3rem"></span></div></div>
        <button class="btn btn-primary" style="margin-top:1rem" onclick="saveCfg()">💾 ${t('btn.save')}</button></div>`;
  } catch (e) { el.innerHTML = `<div class="card"><h2>${t('common.error')}</h2><p>${esc(e.message)}</p></div>`; }
}

async function saveCfg() {
  try {
    const sys = {};
    // TTS
    const ttsBackend = $val('cfg-tts');
    sys.models = sys.models || {};
    sys.models.tts_backend = ttsBackend;
    const ttsKey = ttsBackend.replace(/-/g, '_');
    const ttsUrl = $val('cfg-tts-url');
    const ttsApiKey = $val('cfg-tts-key');
    const ttsCfg = {};
    if (ttsUrl) ttsCfg.api_url = ttsUrl;
    ttsCfg.api_key = ttsApiKey || '';  // 保存空串可清除旧 key
    sys.models[ttsKey] = ttsCfg;
    // LipSync
    const lsBackend = $val('cfg-lipsync');
    sys.models.lip_sync_backend = lsBackend;
    const lsKey = lsBackend.replace(/-/g, '_');
    const lsUrl = $val('cfg-lipsync-url');
    if (lsUrl) sys.models[lsKey] = { api_url: lsUrl };
    // ComfyUI
    sys.comfyui = { url: $val('cfg-comfyui'), api_key: $val('cfg-comfyui-key') };
    // LLM
    const llmEnabled = $val('cfg-llm-enabled') === 'true';
    sys.llm = { enabled: llmEnabled, backend: $val('cfg-llm-backend'), base_url: $val('cfg-llm-url'), model: $val('cfg-llm-model'), api_key: $val('cfg-llm-key') };
    // Seko
    const sekoKey = $val('cfg-seko-key');
    if (sekoKey) sys.seko = { api_key: sekoKey };
    // Training
    const trainingUrl = $val('cfg-training-url');
    const trainingTimeout = parseInt($val('cfg-training-timeout')) || 3600;
    const trainingPoll = parseInt($val('cfg-training-poll')) || 10;
    sys.training = { api_url: trainingUrl, timeout: trainingTimeout, poll_interval: trainingPoll };

    await api('/system/config', { method: 'POST', body: sys });
    toast(t('toast.saved'));
    invalidateCache('sysconfig');
  } catch (e) { toast(e.message, 'error'); }
}

// ── 工具测试 ──

function _toggleKeyVis(inpId, btnId) {
  const inp = document.getElementById(inpId || 'cfg-llm-key');
  const btn = document.getElementById(btnId || 'cfg-llm-key-toggle');
  if (!inp) return;
  if (inp.type === 'password') { inp.type = 'text'; if (btn) btn.textContent = '🙈'; }
  else { inp.type = 'password'; if (btn) btn.textContent = '👁'; }
}

async function testTool(name) {
  const btn = document.getElementById(`test-btn-${name}`);
  const resultEl = document.getElementById(`test-result-${name}`);
  if (btn) btn.disabled = true;
  if (resultEl) resultEl.innerHTML = '⏳ 测试中...';
  try {
    const r = await api(`/tools/${name}/test`, { method: 'POST' });
    if (r.ok) {
      if (resultEl) resultEl.innerHTML = `<span style="color:#22c55e">✅ ${esc(r.message)}</span>`;
      toast(`✅ ${name}: ${r.message}`);
    } else {
      if (resultEl) resultEl.innerHTML = `<span style="color:#ef4444">❌ ${esc(r.message)}</span>`;
      toast(`❌ ${name}: ${r.message}`, 'error');
    }
  } catch (e) {
    if (resultEl) resultEl.innerHTML = `<span style="color:#ef4444">❌ ${esc(e.message)}</span>`;
    toast(`❌ ${name}: ${e.message}`, 'error');
  }
  if (btn) btn.disabled = false;
}

async function testTtsPreview() {
  const btn = document.getElementById('test-btn-tts-preview');
  const resultEl = document.getElementById('test-result-tts-preview');
  const text = $val('cfg-tts-test-text') || '你好，这是一段测试语音。';
  if (btn) btn.disabled = true;
  if (resultEl) resultEl.innerHTML = '⏳ 合成中...';
  try {
    const r = await api('/tools/tts', { method: 'POST', body: { text, language: 'zh' } });
    if (r.task_id) {
      // 轮询任务
      const poll = async () => {
        for (let i = 0; i < 60; i++) {
          await new Promise(res => setTimeout(res, 1000));
          let info;
          try { info = await api(`/tasks/${r.task_id}`); } catch { continue; }
          if (info.status === 'success') {
            const audioPath = info.result?.path || info.result?.audio || info.result?.output;
            if (audioPath) {
              const audio = new Audio(`/api/project-file/${audioPath}`);
              audio.play().catch(() => {});
              if (resultEl) resultEl.innerHTML = `<span style="color:#22c55e">✅ 播放中...</span>`;
            } else {
              if (resultEl) resultEl.innerHTML = `<span style="color:#22c55e">✅ 完成</span>`;
            }
            toast('✅ TTS 试听完成');
            if (btn) btn.disabled = false;
            return;
          }
          if (info.status === 'failed' || info.status === 'cancelled') {
            if (resultEl) resultEl.innerHTML = `<span style="color:#ef4444">❌ ${esc(info.error || info.reason || info.status)}</span>`;
            toast(`❌ TTS: ${info.error || info.reason || info.status}`, 'error');
            if (btn) btn.disabled = false;
            return;
          }
        }
        if (resultEl) resultEl.innerHTML = `<span style="color:#eab308">⏰ 超时</span>`;
        if (btn) btn.disabled = false;
      };
      poll();
      return; // 不在下方 re-enable，由 poll 管理
    }
  } catch (e) {
    if (resultEl) resultEl.innerHTML = `<span style="color:#ef4444">❌ ${esc(e.message)}</span>`;
    toast(`❌ TTS: ${e.message}`, 'error');
  }
  if (btn) btn.disabled = false;
}

// ══════════════════════════════════════════════════════════
// 3.1 拖拽排序
// ══════════════════════════════════════════════════════════

function _initSortable() {
  const tbody = document.querySelector('#page-storyboard tbody');
  if (!tbody || !window.Sortable) return;
  Sortable.create(tbody, {
    animation: 150,
    handle: '.drag-handle',
    ghostClass: 'sortable-ghost',
    chosenClass: 'sortable-chosen',
    onEnd: async function(evt) {
      if (evt.oldIndex === evt.newIndex) return;
      const [moved] = shots.splice(evt.oldIndex, 1);
      shots.splice(evt.newIndex, 0, moved);
      pushUndo(t('sb.reordered'));
      try {
        await api(`/storyboard/${ep}`, { method: 'POST', body: { shots } });
        invalidateCache(`storyboard/${ep}`);
        toast(t('sb.reordered'));
      } catch (e) { toast(e.message, 'error'); }
      loadStoryboard();
    }
  });
}

function _initTimelineSortable() {
  const container = document.querySelector('.timeline-container');
  if (!container || !window.Sortable) return;
  Sortable.create(container, {
    animation: 150,
    handle: '.timeline-card',
    ghostClass: 'sortable-ghost',
    chosenClass: 'sortable-chosen',
    onEnd: async function(evt) {
      if (evt.oldIndex === evt.newIndex) return;
      const [moved] = shots.splice(evt.oldIndex, 1);
      shots.splice(evt.newIndex, 0, moved);
      pushUndo(t('sb.reordered'));
      try {
        await api(`/storyboard/${ep}`, { method: 'POST', body: { shots } });
        invalidateCache(`storyboard/${ep}`);
        toast(t('sb.reordered'));
      } catch (e) { toast(e.message, 'error'); }
      loadStoryboard();
    }
  });
}

// ══════════════════════════════════════════════════════════
// 3.2 批量导入/导出
// ══════════════════════════════════════════════════════════

/** CSV 字段转义（处理换行、逗号、引号） */
function _csvEscape(s) {
  const v = String(s || '');
  if (v.includes('"') || v.includes(',') || v.includes('\n') || v.includes('\r')) {
    return `"${v.replace(/"/g, '""')}"`;
  }
  return v;
}

/** CSV 解析（支持多行字段、含引号/逗号的字段） */
function _parseCSV(text) {
  const rows = []; let row = []; let field = ''; let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') { field += '"'; i++; }
        else inQuotes = false;
      } else field += ch;
    } else {
      if (ch === '"') inQuotes = true;
      else if (ch === ',') { row.push(field.trim()); field = ''; }
      else if (ch === '\n' || (ch === '\r' && text[i + 1] === '\n')) {
        if (ch === '\r') i++;
        row.push(field.trim()); field = '';
        if (row.some(f => f)) rows.push(row);
        row = [];
      } else field += ch;
    }
  }
  row.push(field.trim());
  if (row.some(f => f)) rows.push(row);
  return rows;
}

function exportStoryboard() {
  const headers = ['shot_id', 'scene', 'characters', 'action', 'action_en', 'dialogue', 'dialogue_en', 'camera', 'shot_type', 'duration', 'emotion', 'language', 'outfit'];
  const csv = [headers.map(h => _csvEscape(h)).join(',')];
  shots.forEach(s => {
    csv.push(headers.map(h => _csvEscape(s[h])).join(','));
  });
  const blob = new Blob(['\uFEFF' + csv.join('\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a'); a.href = url; a.download = `storyboard_ep${ep}.csv`;
  a.click(); URL.revokeObjectURL(url);
  toast(t('sb.export_done', { n: shots.length }));
}

function showImportDialog() {
  _showOverlay('import-overlay', t('sb.import_title'), `
    <div class="edit-field"><label>${t('sb.import_file')}</label>
      <input type="file" id="import-file" accept=".csv,.json" style="display:block;margin-top:.3rem"></div>
    <div class="edit-field"><label>${t('sb.import_mode')}</label>
      <select id="import-mode"><option value="merge">${t('sb.import_merge')}</option><option value="overwrite">${t('sb.import_overwrite')}</option></select></div>
    <div id="import-status" class="dim" style="margin-top:.5rem"></div>`, `doImport()`, `📥 ${t('sb.import')}`);
}

async function doImport() {
  const fileInput = document.getElementById('import-file');
  const mode = document.getElementById('import-mode')?.value || 'merge';
  const statusEl = document.getElementById('import-status');
  if (!fileInput?.files?.[0]) { toast(t('sb.import_file'), 'error'); return; }

  const file = fileInput.files[0];
  const text = await file.text();
  let newShots = [];

  try {
    if (file.name.endsWith('.json')) {
      const data = JSON.parse(text);
      newShots = Array.isArray(data) ? data : (data.shots || []);
    } else {
      // CSV（支持多行字段）
      const rows = _parseCSV(text);
      if (rows.length < 2) throw new Error('Empty CSV');
      const headers = rows[0];
      for (let i = 1; i < rows.length; i++) {
        const shot = {};
        headers.forEach((h, j) => { shot[h] = rows[i][j] || ''; });
        if (shot.shot_id) newShots.push(shot);
      }
    }
  } catch (e) { _html(statusEl, `❌ ${t('sb.import_parse_err')}: ${e.message}`); return; }

  if (!newShots.length) { _html(statusEl, `❌ ${t('sb.import_parse_err')}`); return; }

  const finalShots = mode === 'overwrite' ? newShots : [...(await api(`/storyboard/${ep}`)).shots, ...newShots];
  try {
    await api(`/storyboard/${ep}`, { method: 'POST', body: { shots: finalShots } });
    shots = finalShots;
    invalidateCache(`storyboard/${ep}`);
    document.getElementById('import-overlay')?.remove();
    toast(t('sb.import_done', { n: newShots.length }));
    loadStoryboard();
  } catch (e) { toast(e.message, 'error'); }
}

// ══════════════════════════════════════════════════════════
// 3.3 引用计数
// ══════════════════════════════════════════════════════════

async function _getRefCounts(type) {
  try {
    const eps = await loadEpisodeSelector();
    const counts = {};
    for (const e of eps) {
      const d = await cachedFetch(`storyboard/${e}`, () => api(`/storyboard/${e}`));
      (d.shots || []).forEach(s => {
        const names = (type === 'characters' ? s.characters : s.scene) || '';
        names.split(/[,、]/).map(n => n.trim()).filter(Boolean).forEach(n => { counts[n] = (counts[n] || 0) + 1; });
      });
    }
    return counts;
  } catch { return {}; }
}

async function deleteCharWithRef(id) {
  const counts = await _getRefCounts('characters');
  const count = counts[id] || 0;
  if (count > 0) {
    if (!await modalConfirm(t('char.confirm_delete_ref', { n: count }))) return;
  }
  _crudDelete('characters', id, t('char.title'), loadCharacters);
}

async function deleteSceneWithRef(id) {
  const counts = await _getRefCounts('scenes');
  const count = counts[id] || 0;
  if (count > 0) {
    if (!await modalConfirm(t('scene.confirm_delete_ref', { n: count }))) return;
  }
  _crudDelete('scenes', id, t('scene.title'), loadScenes);
}

// ══════════════════════════════════════════════════════════
// 3.4 配置预设模板
// ══════════════════════════════════════════════════════════

const CONFIG_PRESETS = {
  local_comfyui: {
    tts: { backend: 'gpt-sovits', url: 'http://127.0.0.1:9880' },
    lipsync: { backend: 'sadtalker', url: 'http://127.0.0.1:7860' },
    comfyui: { url: 'http://127.0.0.1:8188', api_key: '' },
    llm: { enabled: false, backend: 'ollama', base_url: 'http://127.0.0.1:11434', model: 'qwen2.5:7b', api_key: '' },
  },
  cloud_siliconflow: {
    tts: { backend: 'mimo-voicedesign', url: 'https://api.siliconflow.cn/v1' },
    lipsync: { backend: 'musetalk', url: 'http://127.0.0.1:7860' },
    comfyui: { url: 'http://127.0.0.1:8188', api_key: '' },
    llm: { enabled: true, backend: 'openai', base_url: 'https://api.siliconflow.cn/v1', model: 'Qwen/Qwen2.5-7B-Instruct', api_key: '' },
  },
  ollama_local: {
    tts: { backend: 'mimo-voicedesign', url: '' },
    lipsync: { backend: 'musetalk', url: 'http://127.0.0.1:7860' },
    comfyui: { url: 'http://127.0.0.1:8188', api_key: '' },
    llm: { enabled: true, backend: 'ollama', base_url: 'http://127.0.0.1:11434', model: 'qwen2.5:7b', api_key: '' },
  },
};

function applyPreset(key) {
  const p = CONFIG_PRESETS[key];
  if (!p) return;
  // TTS
  const ttsSel = document.getElementById('cfg-tts');
  if (ttsSel) { ttsSel.value = p.tts.backend; }
  const ttsUrl = document.getElementById('cfg-tts-url');
  if (ttsUrl) ttsUrl.value = p.tts.url;
  // LipSync
  const lsSel = document.getElementById('cfg-lipsync');
  if (lsSel) { lsSel.value = p.lipsync.backend; }
  const lsUrl = document.getElementById('cfg-lipsync-url');
  if (lsUrl) lsUrl.value = p.lipsync.url;
  // ComfyUI
  const cuUrl = document.getElementById('cfg-comfyui');
  if (cuUrl) cuUrl.value = p.comfyui.url;
  const cuKey = document.getElementById('cfg-comfyui-key');
  if (cuKey) cuKey.value = p.comfyui.api_key || '';
  // LLM
  const llmEnabled = document.getElementById('cfg-llm-enabled');
  if (llmEnabled) llmEnabled.value = String(p.llm.enabled);
  const llmBackend = document.getElementById('cfg-llm-backend');
  if (llmBackend) llmBackend.value = p.llm.backend;
  const llmUrl = document.getElementById('cfg-llm-url');
  if (llmUrl) llmUrl.value = p.llm.base_url;
  const llmModel = document.getElementById('cfg-llm-model');
  if (llmModel) llmModel.value = p.llm.model;
  toast(t('set.preset_applied'));
  saveCfg();
}

// ══════════════════════════════════════════════════════════
// 3.5 成片预览
// ══════════════════════════════════════════════════════════

async function _loadFinalPreview() {
  const el = document.getElementById('final-preview-area');
  if (!el) return;
  try {
    const r = await api(`/shots/${ep}/final/resources`).catch(() => ({ resources: {} }));
    if (r.resources?.final) {
      const fname = r.resources.final;
      el.innerHTML = `<div class="final-preview-wrap">
        <video controls src="/api/files/${ep}/final/${fname}" style="max-width:100%;max-height:400px;border-radius:8px;background:#000"></video>
        <div style="margin-top:.5rem"><a href="/api/files/${ep}/final/${fname}" download class="btn btn-outline">⬇ ${t('wb.download')}</a></div></div>`;
    } else {
      el.innerHTML = `<div class="final-preview-wrap"><div style="font-size:2rem;opacity:.3">🎬</div><p class="dim">${t('wb.no_final')}</p><p class="dim" style="font-size:.76rem">${t('wb.no_final_hint')}</p></div>`;
    }
  } catch {
    el.innerHTML = `<div class="final-preview-wrap"><div style="font-size:2rem;opacity:.3">🎬</div><p class="dim">${t('wb.no_final')}</p></div>`;
  }
}

// ══════════════════════════════════════════════════════════
// 4.1 对话式编辑
// ══════════════════════════════════════════════════════════

let _chatOpen = false;
let _chatHistory = [];
let _chatSending = false;

function toggleChat() {
  _chatOpen = !_chatOpen;
  let panel = document.getElementById('chat-panel');
  if (_chatOpen) {
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'chat-panel';
      panel.className = 'chat-panel';
      panel.innerHTML = `<div class="chat-header"><span>${t('chat.title')}</span><button class="btn btn-xs btn-outline" onclick="toggleChat()">✕</button></div>
        <div class="chat-messages" id="chat-messages"></div>
        <div class="chat-input-row"><textarea id="chat-input" rows="2" placeholder="${t('chat.placeholder')}" onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendChatMsg()}"></textarea>
          <button class="btn btn-primary" onclick="sendChatMsg()">${t('chat.send')}</button></div>`;
      document.body.appendChild(panel);
    }
    panel.style.display = 'flex';
    document.getElementById('chat-input')?.focus();
    _renderChatHistory();
  } else if (panel) {
    panel.style.display = 'none';
  }
}

function _renderChatHistory() {
  const el = document.getElementById('chat-messages');
  if (!el) return;
  el.innerHTML = _chatHistory.map(m => `<div class="chat-msg chat-msg-${m.role}">${esc(m.text)}</div>`).join('');
  el.scrollTop = el.scrollHeight;
}

async function sendChatMsg() {
  if (_chatSending) return;
  const input = document.getElementById('chat-input');
  const text = input?.value?.trim();
  if (!text) { toast(t('chat.empty'), 'error'); return; }
  input.value = '';
  _chatSending = true;
  _chatHistory.push({ role: 'user', text });
  if (_chatHistory.length > 100) _chatHistory.splice(0, _chatHistory.length - 100);
  _renderChatHistory();

  _chatHistory.push({ role: 'ai', text: t('chat.thinking') });
  _renderChatHistory();

  try {
    const { task_id } = await api('/llm/chat-edit', { method: 'POST', body: { episode: ep, message: text, shots } });
    const result = await pollTask(task_id);
    _chatHistory.pop(); // remove thinking

    if (result.status === 'success' && result.result?.status === 'done') {
      const r = result.result;
      _chatHistory.push({ role: 'ai', text: `${t('chat.success')}\n${r.message || ''}` });
      if (r.shots && Array.isArray(r.shots)) {
        // 校验并补全缺失字段
        const defaults = { shot_id: '', scene: '', characters: '', action: '', dialogue: '', camera: '固定', shot_type: '中景', duration: 4, emotion: 'neutral', language: 'zh', outfit: '', action_en: '', dialogue_en: '' };
        r.shots = r.shots.map((s, i) => {
          const merged = { ...defaults, ...s };
          if (!merged.shot_id) merged.shot_id = String(i + 1).padStart(3, '0');
          merged.duration = parseInt(merged.duration) || 4;
          return merged;
        });
        shots = r.shots;
        await api(`/storyboard/${ep}`, { method: 'POST', body: { shots } });
        invalidateCache(`storyboard/${ep}`);
        const p = document.querySelector('.page.active');
        if (p?.id === 'page-storyboard') loadStoryboard();
        else if (p?.id === 'page-pipeline') { renderShotsGrid(); }
      }
    } else {
      const err = result.result?.reason || result.error || t('chat.error');
      _chatHistory.push({ role: 'err', text: `❌ ${err}` });
    }
  } catch (e) {
    _chatHistory.pop();
    _chatHistory.push({ role: 'err', text: `❌ ${e.message}` });
  }
  _chatSending = false;
  _renderChatHistory();
}

// ══════════════════════════════════════════════════════════
// 4.2 主体库管理
// ══════════════════════════════════════════════════════════

async function loadAssets() {
  const el = document.getElementById('page-assets');
  el.innerHTML = `<div class="card"><h2>${t('common.loading')}</h2></div>`;
  try {
    const [charData, sceneData] = await Promise.all([
      api('/assets/shared/characters').catch(() => ({ assets: [] })),
      api('/assets/shared/scenes').catch(() => ({ assets: [] })),
    ]);
    const chars = charData.assets || [];
    const scenes = sceneData.assets || [];

    const charCards = chars.map(c => {
      const thumb = c.reference_images?.length ? `<img src="${esc(c.reference_images[0])}" loading="lazy">` : '👤';
      return `<div class="asset-card"><div class="asset-card-thumb">${thumb}</div><div class="asset-card-info"><h4>${esc(c.name || c.id)}</h4><p>${esc(c.appearance || '')}</p></div><button class="btn btn-xs btn-outline" onclick="copyAssetToProject('characters','${esc(c.id)}')">${t('asset.copy_to_proj')}</button></div>`;
    }).join('');
    const sceneCards = scenes.map(s => {
      const thumb = s.reference_images?.length ? `<img src="${esc(s.reference_images[0])}" loading="lazy">` : '🏔️';
      return `<div class="asset-card"><div class="asset-card-thumb">${thumb}</div><div class="asset-card-info"><h4>${esc(s.name || s.id)}</h4><p>${esc(s.description || '')}</p></div><button class="btn btn-xs btn-outline" onclick="copyAssetToProject('scenes','${esc(s.id)}')">${t('asset.copy_to_proj')}</button></div>`;
    }).join('');

    const allCards = charCards + sceneCards;
    el.innerHTML = `<div class="card"><h2>${t('asset.title')}</h2><p class="dim" style="margin-bottom:1rem">${t('asset.desc')}</p>
      ${allCards ? `<div style="display:flex;flex-direction:column;gap:.5rem">${allCards}</div>` : `<div class="empty-state"><div class="empty-state-icon">📦</div><h3>${t('asset.empty')}</h3><p>${t('asset.empty_hint')}</p></div>`}</div>`;
  } catch (e) { el.innerHTML = `<div class="card"><h2>${t('common.error')}</h2><p>${esc(e.message)}</p></div>`; }
}

async function copyAssetToProject(type, id) {
  try {
    await api(`/assets/shared/${type}/${id}/copy`, { method: 'POST' });
    invalidateCache(type);
    toast(t('asset.copied'));
  } catch (e) { toast(e.message, 'error'); }
}

async function addToSharedLibrary(type, id) {
  try {
    await api(`/assets/${type}/${id}/share`, { method: 'POST' });
    toast(t('asset.copied'));
  } catch (e) { toast(e.message, 'error'); }
}

// ══════════════════════════════════════════════════════════
// 4.3 多剧集管理
// ══════════════════════════════════════════════════════════

async function loadEpisodeManager() {
  // This is embedded in the projects page
  const el = document.getElementById('ep-manager');
  if (!el) return;
  try {
    const d = await api('/episodes/summary');
    const episodes = d.episodes || [];
    if (!episodes.length) {
      el.innerHTML = `<div class="card" style="margin-top:1rem"><h2>${t('ep.title')}</h2><p class="dim">暂无剧集</p></div>`;
      return;
    }
    const cards = episodes.map(ep => {
      const statusKey = `ep.status_${ep.status}`;
      const badgeClass = ep.status === 'done' ? 'badge-green' : ep.status === 'progress' ? 'badge' : '';
      return `<div class="ep-card" onclick="ep=${ep.episode};navTo('pipeline')"><div class="ep-card-num">EP ${ep.episode}</div><div class="ep-card-meta">${ep.shots} ${t('ep.shots')} · ${ep.duration}s · ${ep.done}/${ep.shots} ✅</div><div class="ep-card-status"><span class="badge ${badgeClass}">${t(statusKey)}</span></div></div>`;
    });
    el.innerHTML = `<div class="card" style="margin-top:1rem"><h2>${t('ep.title')}</h2><div class="ep-grid">${cards.join('')}</div></div>`;
  } catch (e) { el.innerHTML = `<div class="dim">${e.message}</div>`; }
}

// ══════════════════════════════════════════════════════════
// 4.4 Worker 实时状态
// ══════════════════════════════════════════════════════════

async function _updateWorkerStatus() {
  const el = document.getElementById('sidebar-worker');
  if (!el) return;
  try {
    const r = await api('/system/workers').catch(() => ({ active: 0, status: 'offline' }));
    if (r.status === 'offline') {
      el.innerHTML = `<span class="status-dot err"></span> ${t('worker.offline')}`;
    } else if (r.active > 0) {
      el.innerHTML = `<span class="status-dot ok"></span> ${t('worker.running')} · ${t('worker.tasks', { n: r.active })}`;
    } else {
      el.innerHTML = `<span class="status-dot ok"></span> ${t('worker.idle')}`;
    }
  } catch {
    el.innerHTML = `<span class="status-dot err"></span> ${t('worker.offline')}`;
  }
}

// Poll worker status every 15 seconds
setInterval(_updateWorkerStatus, 15000);

applyI18n();
_updateWorkerStatus();
loadDashboard();

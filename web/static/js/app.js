// AI 短剧工作台 v2 — 前端应用
const API = '/api';

// ── 工具函数 ──
async function api(path, opts = {}) {
  const r = await fetch(API + path, {
    headers: { 'Content-Type': 'application/json', ...opts.headers },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!r.ok) {
    const text = await r.text();
    try { const j = JSON.parse(text); throw new Error(j.detail || text); }
    catch(e) { if (e.message) throw e; throw new Error(text); }
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

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'onclick') el.onclick = v;
    else if (k === 'className') el.className = v;
    else el.setAttribute(k, v);
  }
  for (const c of children) {
    if (typeof c === 'string') el.appendChild(document.createTextNode(c));
    else if (c) el.appendChild(c);
  }
  return el;
}

// ── 任务轮询 ──
async function pollTask(taskId, onProgress) {
  while (true) {
    const info = await api(`/tasks/${taskId}`);
    if (onProgress) onProgress(info);
    if (['success', 'failed', 'cancelled'].includes(info.status)) return info;
    await new Promise(r => setTimeout(r, 800));
  }
}

// ── 页面路由 ──
document.querySelectorAll('.nav-item').forEach(item => {
  item.onclick = () => {
    document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    item.classList.add('active');
    document.getElementById(`page-${item.dataset.page}`).classList.add('active');
    loadPage(item.dataset.page);
  };
});

function navTo(page) {
  document.querySelector(`.nav-item[data-page="${page}"]`).click();
}

async function loadPage(page) {
  const loaders = { dashboard: loadDashboard, characters: loadCharacters, scenes: loadScenes,
                    storyboard: loadStoryboard, pipeline: loadPipeline, projects: loadProjects,
                    settings: loadSettings };
  if (loaders[page]) await loaders[page]();
}

// ══════════════════════════════════════════════════════════
// 工具状态组件
// ══════════════════════════════════════════════════════════

const TOOL_META = {
  redis:    { icon: '🔴', label: 'Redis',       desc: '任务队列（必选）', type: 'infra' },
  celery:   { icon: '🔧', label: 'Celery Worker', desc: '异步任务处理（必选）', type: 'infra' },
  tts:      { icon: '🎤', label: 'TTS 语音',     desc: '文字转语音', type: 'ai' },
  comfyui:  { icon: '🎨', label: 'ComfyUI',      desc: '图片/视频生成（GPU）', type: 'gpu' },
  lipsync:  { icon: '👄', label: '口型同步',      desc: 'LipSync（GPU）', type: 'gpu' },
  llm:      { icon: '🧠', label: 'LLM 大模型',   desc: '文本生成/翻译', type: 'gpu' },
  music:    { icon: '🎵', label: '配乐',          desc: '背景音乐生成', type: 'ai' },
  ffmpeg:   { icon: '🎞️', label: 'FFmpeg',       desc: '音视频处理（必选）', type: 'infra' },
};

function renderToolCard(name, info) {
  const meta = TOOL_META[name] || { icon: '❓', label: name, desc: '', type: 'other' };
  const ok = info.available;
  const statusClass = ok ? 'tool-ok' : (meta.type === 'infra' ? 'tool-err' : 'tool-off');
  const statusText = ok ? '可用' : (info.reason || '不可用');
  const typeBadge = { infra: 'badge-red', gpu: 'badge-purple', ai: 'badge-blue' }[meta.type] || 'badge-gray';

  return `
    <div class="tool-card ${statusClass}">
      <div class="tool-header">
        <span class="tool-icon">${meta.icon}</span>
        <span class="tool-name">${meta.label}</span>
        <span class="badge ${typeBadge}">${meta.type}</span>
      </div>
      <div class="tool-desc">${meta.desc}</div>
      <div class="tool-status">
        <span class="status-dot ${ok ? 'ok' : 'err'}"></span>
        <span>${statusText}</span>
        ${info.backend ? `<span class="tool-backend">[${info.backend}]</span>` : ''}
      </div>
      ${info.url ? `<div class="tool-url">${info.url}</div>` : ''}
    </div>`;
}

async function loadToolStatus() {
  try {
    const data = await api('/tools');
    return data.tools;
  } catch {
    return {};
  }
}

// ══════════════════════════════════════════════════════════
// 仪表盘
// ══════════════════════════════════════════════════════════

async function loadDashboard() {
  const el = document.getElementById('page-dashboard');
  el.innerHTML = '<div class="card"><h2>⏳ 加载中...</h2></div>';
  try {
    const status = await api('/system/status');
    const tools = status.tools;
    const infra = ['redis', 'celery', 'ffmpeg'];
    const ai = ['tts', 'music'];
    const gpu = ['comfyui', 'lipsync', 'llm'];

    el.innerHTML = `
      <div class="card">
        <h2>📊 系统状态</h2>
        <div class="section-label">基础设施（必选）</div>
        <div class="tool-grid">${infra.map(n => renderToolCard(n, tools[n] || {})).join('')}</div>
        <div class="section-label">AI 工具（按需开启）</div>
        <div class="tool-grid">${ai.map(n => renderToolCard(n, tools[n] || {})).join('')}</div>
        <div class="section-label">GPU 工具（昂贵，按需开启）</div>
        <div class="tool-grid">${gpu.map(n => renderToolCard(n, tools[n] || {})).join('')}</div>
      </div>
      <div class="card">
        <h2>🚀 快速操作</h2>
        <div class="quick-actions">
          <button class="btn btn-primary" onclick="navTo('storyboard')">📝 编辑分镜</button>
          <button class="btn btn-success" onclick="navTo('pipeline')">🎬 生产管线</button>
          <button class="btn btn-outline" onclick="navTo('settings')">⚙️ 配置工具</button>
        </div>
      </div>`;
  } catch (e) {
    el.innerHTML = `<div class="card"><h2>❌ 连接失败</h2><p>${e.message}</p></div>`;
  }
}

// ══════════════════════════════════════════════════════════
// 生产管线 — 每个步骤独立可执行
// ══════════════════════════════════════════════════════════

async function loadPipeline() {
  const el = document.getElementById('page-pipeline');
  const tools = await loadToolStatus();

  const steps = [
    { id: 'tts',        icon: '🎤', name: 'TTS 合成',   desc: '台词 → 音频',             need: ['tts'],     api: '/steps/tts' },
    { id: 'firstframe', icon: '🎨', name: '首帧生成',   desc: '镜头描述 → 首帧图片',      need: ['comfyui'], api: '/steps/first-frame' },
    { id: 'video',      icon: '🎬', name: '视频生成',   desc: '首帧 → 视频片段',          need: ['comfyui'], api: '/steps/video' },
    { id: 'lipsync',    icon: '👄', name: '口型同步',   desc: '视频 + 音频 → 同步视频',   need: ['lipsync'], api: '/steps/lipsync' },
    { id: 'subtitle',   icon: '📝', name: '字幕生成',   desc: '从分镜表生成 SRT 字幕',    need: ['ffmpeg'],  api: '/tools/subtitle' },
    { id: 'music',      icon: '🎵', name: '配乐生成',   desc: '生成背景音乐',             need: ['music'],   api: '/tools/music' },
    { id: 'post',       icon: '🎞️', name: '后期合成',   desc: '拼接 + 字幕 + BGM',        need: ['ffmpeg'],  api: '/tools/post' },
  ];

  // 一键流程
  const fullSteps = [
    { id: 'preview',  icon: '👁️', name: '快速预览',  desc: '低分辨率快速预览', need: ['tts', 'comfyui'] },
    { id: 'produce',  icon: '🎬', name: '完整生产',  desc: '全分辨率全流程',   need: ['tts', 'comfyui', 'lipsync', 'ffmpeg'] },
  ];

  function canRun(needs) {
    return needs.every(n => tools[n]?.available);
  }

  function renderStep(step, isFull = false) {
    const available = canRun(step.need);
    const missingDeps = step.need.filter(n => !tools[n]?.available);
    const missing = missingDeps.map(n => TOOL_META[n]?.label || n).join(', ');
    const action = isFull ? `runFull('${step.id}')` : `runStep('${step.api}', '${step.id}')`;

    return `
      <div class="step-card ${available ? 'step-ready' : 'step-blocked'}">
        <div class="step-icon">${step.icon}</div>
        <div class="step-info">
          <div class="step-name">${step.name}</div>
          <div class="step-desc">${step.desc}</div>
          ${!available ? `<div class="step-missing">⚠ 缺少: ${missing}</div>` : ''}
        </div>
        <button class="btn ${available ? 'btn-primary' : 'btn-disabled'}"
                ${available ? `onclick="${action}"` : 'disabled'}>
          ${available ? '执行' : '不可用'}
        </button>
      </div>`;
  }

  el.innerHTML = `
    <div class="card">
      <h2>🔧 单步工具 — 按需执行，用哪个开哪个</h2>
      <p class="dim">每个工具独立运行，不需要的 GPU 工具可以不开，节省成本</p>
      <div class="step-list">${steps.map(s => renderStep(s)).join('')}</div>
    </div>
    <div class="card">
      <h2>⚡ 一键流程 — 自动编排所有步骤</h2>
      <div class="step-list">${fullSteps.map(s => renderStep(s, true)).join('')}</div>
    </div>
    <div class="card" id="task-monitor" style="display:none">
      <h2>📡 任务进度</h2>
      <div id="task-progress"></div>
    </div>`;
}

async function runStep(apiPath, stepId) {
  const monitor = document.getElementById('task-monitor');
  const progressEl = document.getElementById('task-progress');
  monitor.style.display = 'block';

  // 按步骤构建请求参数
  let body = {};
  const perShotSteps = ['tts', 'firstframe', 'video', 'lipsync'];

  if (perShotSteps.includes(stepId)) {
    // 镜头级步骤：需要 episode + shot_id
    const shotId = prompt('镜头 ID (如 001):', '001');
    if (!shotId) return;
    body = { episode: 1, shot_id: shotId };
  } else if (stepId === 'subtitle') {
    body = { episode: 1 };
  } else if (stepId === 'music') {
    const duration = parseFloat(prompt('时长（秒）:', '30'));
    if (!duration) return;
    body = { duration, mood: 'neutral' };
  } else if (stepId === 'post') {
    body = { episode: 1, vertical: false };
  }

  progressEl.innerHTML = `<div class="task-running">⏳ 提交中...</div>`;

  try {
    const r = await fetch(API + apiPath, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const text = await r.text();
      let msg = text;
      try { const j = JSON.parse(text); msg = j.detail || text; } catch {}
      throw new Error(msg);
    }
    const data = await r.json();
    progressEl.innerHTML = `<div class="task-running">⏳ 任务 ${data.task_id} 执行中...</div>`;

    const result = await pollTask(data.task_id, (info) => {
      progressEl.innerHTML = `
        <div class="task-info">
          <div class="task-bar"><div class="task-fill" style="width:${info.progress}%"></div></div>
          <div class="task-text">${info.message || info.stage || '处理中...'} (${info.progress}%)</div>
        </div>`;
    });

    if (result.status === 'success') {
      progressEl.innerHTML = `<div class="task-done">✅ 完成${result.result?.path ? ': ' + result.result.path : ''}</div>`;
      toast('✅ 完成');
    } else {
      progressEl.innerHTML = `<div class="task-fail">❌ 失败: ${result.error || '未知错误'}</div>`;
      toast(result.error || '失败', 'error');
    }
  } catch (e) {
    progressEl.innerHTML = `<div class="task-fail">❌ ${e.message}</div>`;
    toast(e.message, 'error');
  }
}

async function runFull(cmd) {
  const monitor = document.getElementById('task-monitor');
  const progressEl = document.getElementById('task-progress');
  monitor.style.display = 'block';
  progressEl.innerHTML = `<div class="task-running">⏳ 提交 ${cmd}...</div>`;

  try {
    const r = await fetch(API + '/pipeline/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ episode: 1, command: cmd }),
    });
    if (!r.ok) {
      const text = await r.text();
      let msg = text;
      try { const j = JSON.parse(text); msg = j.detail || text; } catch {}
      throw new Error(msg);
    }
    const data = await r.json();
    progressEl.innerHTML = `<div class="task-running">⏳ 任务执行中...</div>`;

    const result = await pollTask(data.task_id, (info) => {
      progressEl.innerHTML = `
        <div class="task-info">
          <div class="task-bar"><div class="task-fill" style="width:${info.progress}%"></div></div>
          <div class="task-text">${info.message || info.stage || '处理中...'} (${info.progress}%)</div>
        </div>`;
    });

    if (result.status === 'success') {
      progressEl.innerHTML = `<div class="task-done">✅ 完成</div>`;
      toast('✅ 完成');
    } else {
      progressEl.innerHTML = `<div class="task-fail">❌ ${result.error || '失败'}</div>`;
      toast(result.error || '失败', 'error');
    }
  } catch (e) {
    progressEl.innerHTML = `<div class="task-fail">❌ ${e.message}</div>`;
    toast(e.message, 'error');
  }
}

// ══════════════════════════════════════════════════════════
// 角色管理
// ══════════════════════════════════════════════════════════

async function loadCharacters() {
  const el = document.getElementById('page-characters');
  try {
    const data = await api('/characters');
    const chars = data.characters || [];
    let rows = chars.map(c => `
      <tr>
        <td>${c.id || ''}</td>
        <td>${c.name || ''}</td>
        <td>${c.gender || ''}</td>
        <td>${(c.appearance || '').substring(0, 50)}</td>
        <td><button class="btn btn-sm btn-primary" onclick="editChar('${c.id}')">编辑</button></td>
      </tr>`).join('');
    el.innerHTML = `
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">
          <h2>👤 角色管理</h2>
          <button class="btn btn-success" onclick="newChar()">+ 新建角色</button>
        </div>
        <table><thead><tr><th>ID</th><th>姓名</th><th>性别</th><th>外观</th><th>操作</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="5" class="dim" style="text-align:center">暂无角色</td></tr>'}</tbody></table>
      </div>`;
  } catch (e) {
    el.innerHTML = `<div class="card"><h2>❌ 加载失败</h2><p>${e.message}</p></div>`;
  }
}

function newChar() {
  const id = prompt('角色 ID (英文):');
  if (!id) return;
  const name = prompt('角色姓名:');
  if (!name) return;
  api('/characters', { method: 'POST', body: { id, name, gender: '', appearance: '', outfits: {}, voice: {} } })
    .then(() => { toast('角色已创建'); loadCharacters(); })
    .catch(e => toast(e.message, 'error'));
}

function editChar(id) { toast('编辑功能开发中', 'error'); }

// ══════════════════════════════════════════════════════════
// 场景管理
// ══════════════════════════════════════════════════════════

async function loadScenes() {
  const el = document.getElementById('page-scenes');
  try {
    const data = await api('/scenes');
    const scenes = data.scenes || [];
    let rows = scenes.map(s => `
      <tr>
        <td>${s.id || ''}</td><td>${s.name || ''}</td>
        <td>${(s.description || '').substring(0, 50)}</td><td>${s.lighting || ''}</td>
      </tr>`).join('');
    el.innerHTML = `
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">
          <h2>🏔️ 场景管理</h2>
          <button class="btn btn-success" onclick="newScene()">+ 新建场景</button>
        </div>
        <table><thead><tr><th>ID</th><th>名称</th><th>描述</th><th>灯光</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="4" class="dim" style="text-align:center">暂无场景</td></tr>'}</tbody></table>
      </div>`;
  } catch (e) {
    el.innerHTML = `<div class="card"><h2>❌ 加载失败</h2><p>${e.message}</p></div>`;
  }
}

function newScene() {
  const id = prompt('场景 ID (英文):');
  if (!id) return;
  const name = prompt('场景名称:');
  if (!name) return;
  api('/scenes', { method: 'POST', body: { id, name, description: '', lighting: '' } })
    .then(() => { toast('场景已创建'); loadScenes(); })
    .catch(e => toast(e.message, 'error'));
}

// ══════════════════════════════════════════════════════════
// 分镜表
// ══════════════════════════════════════════════════════════

async function loadStoryboard() {
  const el = document.getElementById('page-storyboard');
  try {
    const data = await api('/storyboard/1');
    const shots = data.shots || [];
    let rows = shots.map((s, i) => `
      <tr>
        <td>${s.shot_id || i + 1}</td><td>${s.scene || ''}</td><td>${s.characters || ''}</td>
        <td>${(s.action || '').substring(0, 30)}</td><td>${(s.dialogue || '').substring(0, 30)}</td>
        <td>${s.camera || ''}</td><td>${s.shot_type || ''}</td><td>${s.duration || ''}s</td>
        <td>${s.emotion || ''}</td>
      </tr>`).join('');
    el.innerHTML = `
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">
          <h2>📝 分镜表 — 第1集</h2>
          <div>
            <button class="btn btn-success" onclick="addShot()">+ 添加镜头</button>
          </div>
        </div>
        <table><thead><tr><th>镜号</th><th>场景</th><th>角色</th><th>动作</th><th>台词</th><th>运镜</th><th>景别</th><th>时长</th><th>情绪</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="9" class="dim" style="text-align:center">暂无分镜</td></tr>'}</tbody></table>
      </div>`;
  } catch (e) {
    el.innerHTML = `<div class="card"><h2>❌ 加载失败</h2><p>${e.message}</p></div>`;
  }
}

function addShot() {
  const shot = {
    episode: 1, shot_id: String(document.querySelectorAll('#page-storyboard tbody tr').length + 1).padStart(3, '0'),
    scene: prompt('场景:') || '', characters: prompt('角色:') || '',
    action: prompt('动作:') || '', dialogue: prompt('台词:') || '......',
    camera: '固定', shot_type: '中景', duration: 4, emotion: 'neutral',
  };
  api('/storyboard/1', { method: 'POST', body: { shots: [shot] } })
    .then(() => { toast('镜头已添加'); loadStoryboard(); })
    .catch(e => toast(e.message, 'error'));
}

// ══════════════════════════════════════════════════════════
// 项目管理
// ══════════════════════════════════════════════════════════

async function loadProjects() {
  const el = document.getElementById('page-projects');
  try {
    const data = await api('/projects');
    const projects = data.projects || [];
    let rows = projects.map(p => `
      <tr>
        <td>${p.active ? '→' : ''}</td><td>${p.name}</td>
        <td class="dim" style="font-size:0.75rem">${p.path}</td>
        <td>${p.active ? '<span class="badge badge-green">当前</span>' :
            `<button class="btn btn-sm btn-primary" onclick="switchProj('${p.name}')">切换</button>`}</td>
      </tr>`).join('');
    el.innerHTML = `
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">
          <h2>📂 项目管理</h2>
          <button class="btn btn-success" onclick="newProj()">+ 新建项目</button>
        </div>
        <table><thead><tr><th></th><th>名称</th><th>路径</th><th>状态</th></tr></thead>
        <tbody>${rows}</tbody></table>
      </div>`;
  } catch (e) {
    el.innerHTML = `<div class="card"><h2>❌ 加载失败</h2><p>${e.message}</p></div>`;
  }
}

function newProj() {
  const name = prompt('项目名称:');
  if (!name) return;
  api('/projects/new', { method: 'POST', body: { name } })
    .then(() => { toast('项目已创建'); loadProjects(); })
    .catch(e => toast(e.message, 'error'));
}

function switchProj(name) {
  api('/projects/switch', { method: 'POST', body: { name } })
    .then(() => { toast(`已切换到: ${name}`); loadProjects(); })
    .catch(e => toast(e.message, 'error'));
}

// ══════════════════════════════════════════════════════════
// 系统设置 — 工具管理
// ══════════════════════════════════════════════════════════

async function loadSettings() {
  const el = document.getElementById('page-settings');
  try {
    const [cfg, env, toolsData] = await Promise.all([api('/config'), api('/system/env'), api('/tools')]);
    const tools = toolsData.tools || {};

    // 工具配置表单
    const ttsBackends = ['mimo-voicedesign', 'mimo-voiceclone', 'gpt-sovits', 'cosyvoice', 'fish-speech'];
    const lipsyncBackends = ['musetalk', 'sadtalker', 'wav2lip'];
    const musicBackends = ['template', 'musicgen'];

    el.innerHTML = `
      <div class="card">
        <h2>💻 环境信息</h2>
        <div class="info-grid">
          <div><span class="dim">OS:</span> ${env.os}</div>
          <div><span class="dim">Python:</span> ${env.python}</div>
          <div><span class="dim">GPU:</span> ${env.gpu.available ? env.gpu.name + ' (' + env.gpu.vram_mb + 'MB)' : '不可用（API 模式不受影响）'}</div>
        </div>
      </div>

      <div class="card">
        <h2>🔧 工具配置 — 按需启用，不用的不花钱</h2>
        <p class="dim">修改后保存，工具会自动检测可用性</p>

        <div class="config-section">
          <h3>🎤 TTS 语音合成</h3>
          <div class="form-row">
            <label>后端</label>
            <select id="cfg-tts">${ttsBackends.map(b =>
              `<option value="${b}" ${cfg.models?.tts_backend === b ? 'selected' : ''}>${b}</option>`).join('')}</select>
          </div>
          <div class="form-row">
            <label>API 地址</label>
            <input id="cfg-tts-url" value="${cfg.models?.gpt_sovits?.api_url || 'http://127.0.0.1:9880'}"
                   placeholder="GPT-SoVITS/CosyVoice 等服务地址">
          </div>
          <div class="tool-status-inline">
            <span class="status-dot ${tools.tts?.available ? 'ok' : 'err'}"></span>
            ${tools.tts?.available ? '可用' : tools.tts?.reason || '不可用'}
          </div>
        </div>

        <div class="config-section">
          <h3>🎨 ComfyUI（图片/视频 — GPU）</h3>
          <div class="form-row">
            <label>地址</label>
            <input id="cfg-comfyui" value="${cfg.comfyui?.url || 'http://127.0.0.1:8188'}">
          </div>
          <div class="form-row">
            <label>API Key</label>
            <input id="cfg-comfyui-key" type="password" value="${cfg.comfyui?.api_key || ''}" placeholder="可选">
          </div>
          <div class="tool-status-inline">
            <span class="status-dot ${tools.comfyui?.available ? 'ok' : 'err'}"></span>
            ${tools.comfyui?.available ? '可用' : tools.comfyui?.reason || '不可用'}
          </div>
        </div>

        <div class="config-section">
          <h3>👄 口型同步（GPU）</h3>
          <div class="form-row">
            <label>后端</label>
            <select id="cfg-lipsync">${lipsyncBackends.map(b =>
              `<option value="${b}" ${cfg.models?.lip_sync_backend === b ? 'selected' : ''}>${b}</option>`).join('')}</select>
          </div>
          <div class="form-row">
            <label>API 地址</label>
            <input id="cfg-lipsync-url" value="${cfg.models?.musetalk?.api_url || 'http://127.0.0.1:8080'}">
          </div>
          <div class="tool-status-inline">
            <span class="status-dot ${tools.lipsync?.available ? 'ok' : 'err'}"></span>
            ${tools.lipsync?.available ? '可用' : tools.lipsync?.reason || '不可用'}
          </div>
        </div>

        <div class="config-section">
          <h3>🧠 LLM 大模型（可选）</h3>
          <div class="form-row">
            <label>启用</label>
            <select id="cfg-llm-enabled">
              <option value="false" ${!cfg.llm?.enabled ? 'selected' : ''}>关闭</option>
              <option value="true" ${cfg.llm?.enabled ? 'selected' : ''}>开启</option>
            </select>
          </div>
          <div class="form-row">
            <label>地址</label>
            <input id="cfg-llm-url" value="${cfg.llm?.base_url || 'http://localhost:11434'}">
          </div>
          <div class="form-row">
            <label>模型</label>
            <input id="cfg-llm-model" value="${cfg.llm?.model || 'qwen3:8b'}">
          </div>
        </div>

        <div class="config-section">
          <h3>🎵 配乐</h3>
          <div class="form-row">
            <label>后端</label>
            <select id="cfg-music">${musicBackends.map(b =>
              `<option value="${b}" ${cfg.models?.music_backend === b ? 'selected' : ''}>${b}</option>`).join('')}</select>
          </div>
        </div>

        <button class="btn btn-primary" style="margin-top:1rem" onclick="saveCfg()">💾 保存配置</button>
      </div>`;
  } catch (e) {
    el.innerHTML = `<div class="card"><h2>❌ 加载失败</h2><p>${e.message}</p></div>`;
  }
}

async function saveCfg() {
  try {
    const cfg = await api('/config');
    cfg.models = cfg.models || {};
    cfg.models.tts_backend = document.getElementById('cfg-tts')?.value || cfg.models.tts_backend;
    cfg.models.lip_sync_backend = document.getElementById('cfg-lipsync')?.value || cfg.models.lip_sync_backend;
    cfg.models.music_backend = document.getElementById('cfg-music')?.value || cfg.models.music_backend;
    cfg.models.gpt_sovits = cfg.models.gpt_sovits || {};
    cfg.models.gpt_sovits.api_url = document.getElementById('cfg-tts-url')?.value || '';
    cfg.models.musetalk = cfg.models.musetalk || {};
    cfg.models.musetalk.api_url = document.getElementById('cfg-lipsync-url')?.value || '';
    cfg.comfyui = cfg.comfyui || {};
    cfg.comfyui.url = document.getElementById('cfg-comfyui')?.value || cfg.comfyui.url;
    cfg.comfyui.api_key = document.getElementById('cfg-comfyui-key')?.value || '';
    cfg.llm = cfg.llm || {};
    cfg.llm.enabled = document.getElementById('cfg-llm-enabled')?.value === 'true';
    cfg.llm.base_url = document.getElementById('cfg-llm-url')?.value || '';
    cfg.llm.model = document.getElementById('cfg-llm-model')?.value || '';
    await api('/config', { method: 'POST', body: cfg });
    toast('✅ 配置已保存');
  } catch (e) {
    toast(e.message, 'error');
  }
}

// ── 初始化 ──
loadDashboard();

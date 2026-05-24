// AI 短剧工作台 v2 — 前端应用
const API = '/api';

// ── 工具函数 ──
async function api(path, opts = {}) {
  const r = await fetch(API + path, {
    headers: { 'Content-Type': 'application/json', ...opts.headers },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!r.ok) throw new Error(`API ${r.status}: ${await r.text()}`);
  return r.json();
}

function toast(msg, type = 'success') {
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3000);
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

async function loadPage(page) {
  const loaders = { dashboard: loadDashboard, characters: loadCharacters, scenes: loadScenes,
                    storyboard: loadStoryboard, pipeline: loadPipeline, projects: loadProjects,
                    settings: loadSettings };
  if (loaders[page]) await loaders[page]();
}

// ── 仪表盘 ──
async function loadDashboard() {
  const el = document.getElementById('page-dashboard');
  el.innerHTML = '<div class="card"><h2>⏳ 加载中...</h2></div>';
  try {
    const status = await api('/system/status');
    const s = status.services;
    el.innerHTML = `
      <div class="card"><h2>📊 系统状态</h2>
        <div class="status-grid">
          <div class="status-item"><span class="status-dot ${s.postgresql ? 'ok' : 'err'}"></span> PostgreSQL</div>
          <div class="status-item"><span class="status-dot ${s.redis ? 'ok' : 'err'}"></span> Redis</div>
          <div class="status-item"><span class="status-dot ${s.comfyui ? 'ok' : 'warn'}"></span> ComfyUI</div>
          <div class="status-item"><span class="status-dot ok"></span> TTS: ${status.config.tts}</div>
        </div>
      </div>
      <div class="grid">
        <div class="card"><h2>🚀 快速操作</h2>
          <p style="margin-bottom:0.8rem;color:var(--dim)">版本: ${status.version}</p>
          <button class="btn btn-primary" onclick="navTo('storyboard')">📝 编辑分镜</button>
          <button class="btn btn-success" style="margin-left:0.5rem" onclick="navTo('pipeline')">🎬 开始生产</button>
        </div>
      </div>`;
  } catch (e) {
    el.innerHTML = `<div class="card"><h2>❌ 连接失败</h2><p>${e.message}</p></div>`;
  }
}

function navTo(page) {
  document.querySelector(`.nav-item[data-page="${page}"]`).click();
}

// ── 角色管理 ──
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
        <td>${(c.appearance || '').substring(0, 40)}...</td>
        <td><button class="btn btn-sm btn-primary" onclick="editChar('${c.id}')">编辑</button></td>
      </tr>`).join('');
    el.innerHTML = `
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">
          <h2>👤 角色管理</h2>
          <button class="btn btn-success" onclick="newChar()">+ 新建角色</button>
        </div>
        <table><thead><tr><th>ID</th><th>姓名</th><th>性别</th><th>外观</th><th>操作</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="5" style="text-align:center;color:var(--dim)">暂无角色</td></tr>'}</tbody></table>
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

function editChar(id) {
  toast('编辑功能开发中...', 'error');
}

// ── 场景管理 ──
async function loadScenes() {
  const el = document.getElementById('page-scenes');
  try {
    const data = await api('/scenes');
    const scenes = data.scenes || [];
    let rows = scenes.map(s => `
      <tr>
        <td>${s.id || ''}</td>
        <td>${s.name || ''}</td>
        <td>${(s.description || '').substring(0, 50)}...</td>
        <td>${s.lighting || ''}</td>
      </tr>`).join('');
    el.innerHTML = `
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">
          <h2>🏔️ 场景管理</h2>
          <button class="btn btn-success" onclick="newScene()">+ 新建场景</button>
        </div>
        <table><thead><tr><th>ID</th><th>名称</th><th>描述</th><th>灯光</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="4" style="text-align:center;color:var(--dim)">暂无场景</td></tr>'}</tbody></table>
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

// ── 分镜表 ──
async function loadStoryboard() {
  const el = document.getElementById('page-storyboard');
  try {
    const data = await api('/storyboard/1');
    const shots = data.shots || [];
    let rows = shots.map((s, i) => `
      <tr>
        <td>${s.shot_id || i + 1}</td>
        <td>${s.scene || ''}</td>
        <td>${s.characters || ''}</td>
        <td>${(s.action || '').substring(0, 30)}</td>
        <td>${(s.dialogue || '').substring(0, 30)}</td>
        <td>${s.camera || ''}</td>
        <td>${s.shot_type || ''}</td>
        <td>${s.duration || ''}s</td>
        <td>${s.emotion || ''}</td>
      </tr>`).join('');
    el.innerHTML = `
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">
          <h2>📝 分镜表 — 第1集</h2>
          <div>
            <button class="btn btn-primary" onclick="aiStoryboard()">🚀 AI 快速开始</button>
            <button class="btn btn-success" style="margin-left:0.5rem" onclick="addShot()">+ 添加镜头</button>
          </div>
        </div>
        <table><thead><tr><th>镜号</th><th>场景</th><th>角色</th><th>动作</th><th>台词</th><th>运镜</th><th>景别</th><th>时长</th><th>情绪</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="9" style="text-align:center;color:var(--dim)">暂无分镜，点击「AI 快速开始」生成</td></tr>'}</tbody></table>
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

function aiStoryboard() {
  toast('AI 生成功能需要配置 LLM (Ollama/OpenAI)', 'error');
}

// ── 生产管线 ──
async function loadPipeline() {
  const el = document.getElementById('page-pipeline');
  el.innerHTML = `
    <div class="card">
      <h2>🎬 生产管线</h2>
      <div class="grid" style="margin-top:1rem">
        <div class="card" style="cursor:pointer" onclick="runPipeline('preview')">
          <h2>👁️ 快速预览</h2>
          <p style="color:var(--dim)">快速生成低分辨率预览</p>
        </div>
        <div class="card" style="cursor:pointer" onclick="runPipeline('produce')">
          <h2>🎬 完整生产</h2>
          <p style="color:var(--dim)">全分辨率生产所有镜头</p>
        </div>
        <div class="card" style="cursor:pointer" onclick="runPipeline('post')">
          <h2>🎞️ 后期合成</h2>
          <p style="color:var(--dim)">拼接 + 字幕 + BGM + 调色</p>
        </div>
        <div class="card" style="cursor:pointer" onclick="genPortraits()">
          <h2>🎨 生成定妆照</h2>
          <p style="color:var(--dim)">为所有角色生成参考图</p>
        </div>
      </div>
      <div id="pipeline-log" class="log-box" style="margin-top:1rem;display:none"></div>
    </div>`;
}

async function runPipeline(cmd) {
  const logEl = document.getElementById('pipeline-log');
  logEl.style.display = 'block';
  logEl.textContent = `执行 ${cmd}...\n`;
  try {
    const r = await api('/pipeline/run', { method: 'POST', body: { episode: 1, command: cmd } });
    logEl.textContent += r.stdout || '';
    if (r.stderr) logEl.textContent += `\n[STDERR]\n${r.stderr}`;
    logEl.textContent += `\n\n状态: ${r.status}`;
    toast(r.status === 'ok' ? '✅ 完成' : '❌ 失败', r.status === 'ok' ? 'success' : 'error');
  } catch (e) {
    logEl.textContent += `\n错误: ${e.message}`;
    toast(e.message, 'error');
  }
}

async function genPortraits() {
  try {
    await api('/tools/portraits', { method: 'POST' });
    toast('✅ 定妆照生成完成');
  } catch (e) {
    toast(e.message, 'error');
  }
}

// ── 项目管理 ──
async function loadProjects() {
  const el = document.getElementById('page-projects');
  try {
    const data = await api('/projects');
    const projects = data.projects || [];
    let rows = projects.map(p => `
      <tr>
        <td>${p.active ? '→' : ''}</td>
        <td>${p.name}</td>
        <td style="font-size:0.75rem;color:var(--dim)">${p.path}</td>
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

// ── 系统设置 ──
async function loadSettings() {
  const el = document.getElementById('page-settings');
  try {
    const cfg = await api('/config');
    const env = await api('/system/env');
    el.innerHTML = `
      <div class="card"><h2>💻 环境信息</h2>
        <p>OS: ${env.os}</p>
        <p>Python: ${env.python}</p>
        <p>GPU: ${env.gpu.available ? env.gpu.name + ' (' + env.gpu.vram_mb + 'MB)' : '不可用（API 模式不受影响）'}</p>
      </div>
      <div class="card"><h2>⚙️ 配置</h2>
        <div class="form-group"><label>TTS 后端</label>
          <select id="cfg-tts" onchange="saveCfg()">
            <option value="mimo-voicedesign" ${cfg.models?.tts_backend === 'mimo-voicedesign' ? 'selected' : ''}>MiMo VoiceDesign (免费)</option>
            <option value="gpt-sovits" ${cfg.models?.tts_backend === 'gpt-sovits' ? 'selected' : ''}>GPT-SoVITS</option>
            <option value="cosyvoice" ${cfg.models?.tts_backend === 'cosyvoice' ? 'selected' : ''}>CosyVoice</option>
          </select>
        </div>
        <div class="form-group"><label>口型同步</label>
          <select id="cfg-lipsync">
            <option value="musetalk" ${cfg.models?.lip_sync_backend === 'musetalk' ? 'selected' : ''}>MuseTalk</option>
            <option value="sadtalker" ${cfg.models?.lip_sync_backend === 'sadtalker' ? 'selected' : ''}>SadTalker</option>
          </select>
        </div>
        <div class="form-group"><label>ComfyUI 地址</label>
          <input id="cfg-comfyui" value="${cfg.comfyui?.url || 'http://127.0.0.1:8188'}">
        </div>
        <button class="btn btn-primary" onclick="saveCfg()">保存配置</button>
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
    cfg.comfyui = cfg.comfyui || {};
    cfg.comfyui.url = document.getElementById('cfg-comfyui')?.value || cfg.comfyui.url;
    await api('/config', { method: 'POST', body: cfg });
    toast('✅ 配置已保存');
  } catch (e) {
    toast(e.message, 'error');
  }
}

// ── 初始化 ──
loadDashboard();

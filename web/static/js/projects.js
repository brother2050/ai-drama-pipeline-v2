// MODULE: projects — 项目管理
// ══════════════════════════════════════════════════════════

async function loadProjects() {
  const el = document.getElementById('page-projects');
  el.innerHTML = `<div class="card"><h2>${t('common.loading')}</h2></div>`;
  try {
    const d = await api('/projects');
    const rows = (d.projects || []).map(p => {
      const switchBtn = p.active ? '' : `<button class="btn btn-sm btn-primary" onclick="switchProj('${esc(p.name)}')">${t('common.switch')}</button> `;
      const deleteBtn = (!p.active && !p.isDefault) ? `<button class="btn btn-sm btn-danger" onclick="deleteProj('${esc(p.name)}')">🗑</button>` : '';
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
    if (p) { const pageName = p.id.replace('page-', ''); const fn = PAGES[pageName]; if (fn && typeof window[fn] === 'function') window[fn](); }
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

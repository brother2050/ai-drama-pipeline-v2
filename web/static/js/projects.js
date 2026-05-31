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
async function newProj() {
  // 加载预设列表
  let styles = {}, genres = {};
  try {
    const presets = await api('/projects/presets');
    styles = presets.styles || {};
    genres = presets.genres || {};
  } catch (e) { /* 回退到默认值 */ }

  const styleOpts = Object.entries(styles).map(([k, v]) => `<option value="${k}">${esc(k)} — ${esc(v)}</option>`).join('');
  const genreOpts = Object.entries(genres).map(([k, v]) => `<option value="${k}">${esc(k)} — ${esc(v)}</option>`).join('');

  return new Promise(resolve => {
    const o = document.createElement('div'); o.className = 'edit-overlay';
    o.innerHTML = `<div class="edit-panel" style="width:480px"><div class="edit-header"><h3>🎬 ${t('proj.create_title')}</h3></div>
      <div class="edit-body">
        <div class="edit-field">
          <label style="font-size:.85rem;margin-bottom:.2rem;display:block">${t('proj.name')}</label>
          <input id="_np-name" type="text" placeholder="${t('proj.name_ph')}" style="width:100%">
        </div>
        <div class="edit-field" style="margin-top:.6rem">
          <label style="font-size:.85rem;margin-bottom:.2rem;display:block">${t('proj.style')}</label>
          <select id="_np-style" style="width:100%">${styleOpts}</select>
        </div>
        <div class="edit-field" style="margin-top:.6rem">
          <label style="font-size:.85rem;margin-bottom:.2rem;display:block">${t('proj.genre')}</label>
          <select id="_np-genre" style="width:100%">${genreOpts}</select>
        </div>
      </div>
      <div class="edit-footer"><button class="btn btn-primary" id="_np-ok">${t('btn.confirm')}</button>
      <button class="btn btn-outline" id="_np-cancel">${t('btn.cancel')}</button></div></div>`;
    document.body.appendChild(o);
    const nameInp = o.querySelector('#_np-name');
    const cleanup = (result) => { o.remove(); resolve(result); };
    o.querySelector('#_np-ok').onclick = () => {
      const name = nameInp.value.trim();
      if (!name) { nameInp.focus(); return; }
      cleanup({
        name,
        style: o.querySelector('#_np-style').value,
        genre: o.querySelector('#_np-genre').value,
      });
    };
    o.querySelector('#_np-cancel').onclick = () => cleanup(null);
    o.onclick = (e) => { if (e.target === o) cleanup(null); };
    nameInp.focus();
    nameInp.addEventListener('keydown', (e) => { if (e.key === 'Enter') o.querySelector('#_np-ok').click(); if (e.key === 'Escape') cleanup(null); });
  }).then(result => {
    if (!result) return;
    api('/projects/new', { method: 'POST', body: result }).then(() => {
      toast(t('toast.created'));
      loadProjects();
    }).catch(e => toast(e.message, 'error'));
  });
}
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

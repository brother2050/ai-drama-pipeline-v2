// MODULE: storyboard — 分镜表
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

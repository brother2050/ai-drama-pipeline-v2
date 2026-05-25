// AI 短剧工作台 v2 — 国际化字典
const I18N = {
  // 通用
  'app.title': { zh: '🎬 AI 短剧工作台 v2', en: '🎬 AI Drama Studio v2' },
  'btn.save': { zh: '💾 保存', en: '💾 Save' },
  'btn.cancel': { zh: '取消', en: 'Cancel' },
  'btn.close': { zh: '关闭', en: 'Close' },
  'btn.delete': { zh: '🗑️', en: '🗑️' },
  'btn.edit': { zh: '✏️', en: '✏️' },
  'btn.add': { zh: '+ 新建', en: '+ New' },
  'btn.confirm': { zh: '确认', en: 'Confirm' },

  // 侧边栏
  'nav.dashboard': { zh: '📊 仪表盘', en: '📊 Dashboard' },
  'nav.characters': { zh: '👤 角色管理', en: '👤 Characters' },
  'nav.scenes': { zh: '🏔️ 场景管理', en: '🏔️ Scenes' },
  'nav.storyboard': { zh: '📝 分镜表', en: '📝 Storyboard' },
  'nav.pipeline': { zh: '🎬 生产管线', en: '🎬 Pipeline' },
  'nav.projects': { zh: '📂 项目管理', en: '📂 Projects' },
  'nav.settings': { zh: '⚙️ 系统设置', en: '⚙️ Settings' },

  // 仪表盘
  'dash.title': { zh: '📊 系统状态', en: '📊 System Status' },
  'dash.infra': { zh: '基础设施', en: 'Infrastructure' },
  'dash.ai_tools': { zh: 'AI 工具', en: 'AI Tools' },
  'dash.gpu_tools': { zh: 'GPU 工具', en: 'GPU Tools' },
  'dash.available': { zh: '可用', en: 'Available' },
  'dash.unavailable': { zh: '不可用', en: 'Unavailable' },
  'dash.start': { zh: '🚀 开始', en: '🚀 Get Started' },
  'dash.start_hint': { zh: '进入工作台，选择镜头逐步处理', en: 'Enter the workspace, process shots step by step' },
  'dash.enter_wb': { zh: '🎬 进入工作台', en: '🎬 Enter Workspace' },
  'dash.conn_fail': { zh: '❌ 连接失败', en: '❌ Connection Failed' },

  // 工作台
  'wb.shots_count': { zh: '个镜头', en: 'shots' },
  'wb.batch_tts': { zh: '🎤 批量 TTS', en: '🎤 Batch TTS' },
  'wb.batch_frame': { zh: '🎨 批量首帧', en: '🎨 Batch Frame' },
  'wb.batch_video': { zh: '🎬 批量视频', en: '🎬 Batch Video' },
  'wb.batch_lipsync': { zh: '👄 批量口型', en: '👄 Batch LipSync' },
  'wb.batch_label': { zh: '批量', en: 'Batch' },
  'wb.no_shots': { zh: '暂无分镜', en: 'No shots yet' },
  'wb.no_shots_hint': { zh: '先在分镜表添加镜头', en: 'Add shots in Storyboard first' },
  'wb.go_edit': { zh: '去编辑', en: 'Go Edit' },
  'wb.no_resource': { zh: '暂无资源', en: 'No resources' },
  'wb.esc_hint': { zh: '点击空白处关闭 · ESC 键退出', en: 'Click to close · ESC to exit' },
  'wb.loading': { zh: '⏳ 加载...', en: '⏳ Loading...' },

  // 编辑
  'edit.shot_title': { zh: '✏️ 编辑镜头', en: '✏️ Edit Shot' },
  'edit.scene': { zh: '场景', en: 'Scene' },
  'edit.characters': { zh: '角色', en: 'Characters' },
  'edit.action': { zh: '动作', en: 'Action' },
  'edit.dialogue': { zh: '台词', en: 'Dialogue' },
  'edit.camera': { zh: '运镜', en: 'Camera' },
  'edit.shot_type': { zh: '景别', en: 'Shot Type' },
  'edit.duration': { zh: '时长', en: 'Duration' },
  'edit.emotion': { zh: '情绪', en: 'Emotion' },

  // 批量
  'batch.confirm': { zh: '批量执行 {step}？共 {n} 个镜头', en: 'Batch {step}? {n} shots total' },
  'batch.cancelled': { zh: '已取消', en: 'Cancelled' },
  'batch.done': { zh: '批量完成', en: 'Batch Complete' },

  // 提示
  'toast.saved': { zh: '✅ 已保存', en: '✅ Saved' },
  'toast.deleted': { zh: '✅ 已删除', en: '✅ Deleted' },
  'toast.created': { zh: '已创建', en: 'Created' },
  'toast.switched': { zh: '已切换', en: 'Switched' },
  'toast.cancelled': { zh: '批量已取消', en: 'Batch Cancelled' },
  'toast.timeout': { zh: '轮询超时，请手动检查任务状态', en: 'Polling timeout, check task status manually' },
  'toast.task_done': { zh: '完成', en: 'Done' },
  'toast.task_fail': { zh: '失败', en: 'Failed' },
  'confirm.delete_shot': { zh: '确认删除镜头 {id}？', en: 'Delete shot {id}?' },
  'confirm.delete_char': { zh: '确认删除角色 {id}？', en: 'Delete character {id}?' },
  'confirm.delete_scene': { zh: '确认删除场景 {id}？', en: 'Delete scene {id}?' },
  'confirm.batch': { zh: '批量执行 {step}？共 {n} 个镜头', en: 'Batch {step}? {n} shots' },

  // 角色
  'char.title': { zh: '👤 角色', en: '👤 Characters' },
  'char.none': { zh: '暂无', en: 'None' },
  'char.name': { zh: '姓名', en: 'Name' },
  'char.gender': { zh: '性别', en: 'Gender' },
  'char.appearance': { zh: '外观', en: 'Appearance' },
  'char.operations': { zh: '操作', en: 'Actions' },
  'char.edit_title': { zh: '✏️ 编辑角色', en: '✏️ Edit Character' },

  // 场景
  'scene.title': { zh: '🏔️ 场景', en: '🏔️ Scenes' },
  'scene.none': { zh: '暂无', en: 'None' },
  'scene.name': { zh: '名称', en: 'Name' },
  'scene.desc': { zh: '描述', en: 'Description' },
  'scene.lighting': { zh: '光照', en: 'Lighting' },
  'scene.operations': { zh: '操作', en: 'Actions' },
  'scene.edit_title': { zh: '✏️ 编辑场景', en: '✏️ Edit Scene' },

  // 分镜表
  'sb.title': { zh: '📝 分镜表', en: '📝 Storyboard' },
  'sb.shot_id': { zh: '镜号', en: 'Shot#' },
  'sb.none': { zh: '暂无', en: 'None' },
  'sb.added': { zh: '已添加', en: 'Added' },

  // 项目
  'proj.title': { zh: '📂 项目', en: '📂 Projects' },
  'proj.current': { zh: '当前', en: 'Current' },
  'proj.name': { zh: '名称', en: 'Name' },
  'proj.path': { zh: '路径', en: 'Path' },
  'proj.status': { zh: '状态', en: 'Status' },

  // 设置
  'set.env': { zh: '环境', en: 'Environment' },
  'set.config': { zh: '配置', en: 'Configuration' },
  'set.tts': { zh: 'TTS', en: 'TTS' },
  'set.comfyui': { zh: 'ComfyUI', en: 'ComfyUI' },
  'set.lipsync': { zh: 'LipSync', en: 'LipSync' },
  'set.backend': { zh: '后端', en: 'Backend' },
  'set.address': { zh: '地址', en: 'Address' },
  'set.os': { zh: 'OS', en: 'OS' },
  'set.python': { zh: 'Python', en: 'Python' },
  'set.gpu': { zh: 'GPU', en: 'GPU' },

  // 运镜/景别/情绪
  'camera.fixed': { zh: '固定', en: 'Fixed' },
  'camera.push_in': { zh: '缓慢推近', en: 'Slow Push In' },
  'camera.pan': { zh: '跟随平移', en: 'Follow Pan' },
  'camera.handheld': { zh: '手持晃动', en: 'Handheld' },
  'camera.orbit': { zh: '环绕', en: 'Orbit' },
  'camera.top': { zh: '俯视', en: 'Top Down' },
  'camera.bottom': { zh: '仰视', en: 'Low Angle' },

  'shot.closeup': { zh: '特写', en: 'Close-up' },
  'shot.medium_close': { zh: '近景', en: 'Medium Close' },
  'shot.medium': { zh: '中景', en: 'Medium' },
  'shot.over_shoulder': { zh: '过肩', en: 'Over Shoulder' },
  'shot.full': { zh: '全身', en: 'Full Body' },
  'shot.wide': { zh: '全景', en: 'Wide' },
  'shot.extreme_wide': { zh: '远景', en: 'Extreme Wide' },

  'emo.neutral': { zh: '平静', en: 'Neutral' },
  'emo.happy': { zh: '开心', en: 'Happy' },
  'emo.sad': { zh: '悲伤', en: 'Sad' },
  'emo.angry': { zh: '愤怒', en: 'Angry' },
  'emo.worried': { zh: '担心', en: 'Worried' },
  'emo.surprised': { zh: '惊讶', en: 'Surprised' },
  'emo.calm': { zh: '冷静', en: 'Calm' },
  'emo.determined': { zh: '坚定', en: 'Determined' },

  // 仪表盘补充
  'dash.gpu_unavailable': { zh: '不可用', en: 'Unavailable' },

  // 通用补充
  'common.loading': { zh: '⏳ 加载...', en: '⏳ Loading...' },
  'common.error': { zh: '❌', en: '❌' },
  'common.none': { zh: '暂无', en: 'None' },
  'common.operations': { zh: '操作', en: 'Actions' },
  'common.switch': { zh: '切换', en: 'Switch' },
  'common.current': { zh: '当前', en: 'Current' },
  'common.name': { zh: '名称', en: 'Name' },
  'common.path': { zh: '路径', en: 'Path' },
  'common.status': { zh: '状态', en: 'Status' },

  // 管线补充
  'wb.no_storyboard': { zh: '暂无分镜', en: 'No storyboard' },
  'wb.add_shots_first': { zh: '先在分镜表添加镜头', en: 'Add shots in Storyboard first' },
  'wb.go_edit_btn': { zh: '去编辑', en: 'Go Edit' },
  'wb.gen_portraits': { zh: '📸 定妆照', en: '📸 Portraits' },
  'wb.post_process': { zh: '🎞️ 后期合成', en: '🎞️ Post' },
  'wb.run_all': { zh: '🚀 一键全流程', en: '🚀 Run All' },
  'wb.tools': { zh: '工具', en: 'Tools' },

  // 角色补充
  'char.not_found': { zh: '角色不存在', en: 'Character not found' },
  'char.gender.male': { zh: '男', en: 'Male' },
  'char.gender.female': { zh: '女', en: 'Female' },
  'char.outfits': { zh: '服装', en: 'Outfits' },
  'char.voice': { zh: '语音', en: 'Voice' },
  'char.voice_key': { zh: '语音 Key', en: 'Voice Key' },
  'char.outfit_desc': { zh: '服装描述', en: 'Outfit Description' },

  // 场景补充
  'scene.not_found': { zh: '场景不存在', en: 'Scene not found' },

  // 项目补充
  'proj.created': { zh: '已创建', en: 'Created' },
  'proj.switched': { zh: '已切换', en: 'Switched' },
  'proj.input_name': { zh: '名称:', en: 'Name:' },
  'proj.confirm_delete': { zh: '确认删除项目 {name}？', en: 'Delete project {name}?' },
  'proj.deleted': { zh: '项目已删除', en: 'Project deleted' },

  // 设置补充
  'set.saved': { zh: '✅ 已保存', en: '✅ Saved' },
  'set.gpu_unavailable': { zh: '不可用', en: 'Unavailable' },
  'set.llm': { zh: 'LLM', en: 'LLM' },
  'set.llm_enabled': { zh: '启用', en: 'Enabled' },
  'set.llm_model': { zh: '模型', en: 'Model' },

  // 批量补充
  'batch.cancel_btn': { zh: '⏹ 取消', en: '⏹ Cancel' },
  'batch.close_btn': { zh: '关闭', en: 'Close' },
  'batch.progress': { zh: '{step}...', en: '{step}...' },
  'batch.complete': { zh: '批量完成: {done}成功 {skip}跳过 {fail}失败', en: 'Batch done: {done} OK {skip} skip {fail} fail' },
  'batch.concurrent': { zh: '并发数', en: 'Concurrency' },

  // 步骤名
  'step.tts': { zh: 'TTS', en: 'TTS' },
  'step.first_frame': { zh: '首帧', en: 'Frame' },
  'step.video': { zh: '视频', en: 'Video' },
  'step.lipsync': { zh: '口型同步', en: 'LipSync' },

  // 撤销/重做
  'undo.no_action': { zh: '没有可{label}的操作', en: 'Nothing to {label}' },
  'undo.undo': { zh: '撤销', en: 'Undo' },
  'undo.redo': { zh: '重做', en: 'Redo' },

  // 分镜表补充
  'sb.saved': { zh: '✅ 已保存', en: '✅ Saved' },
  'sb.deleted': { zh: '✅ 已删除', en: '✅ Deleted' },
  'sb.added': { zh: '已添加', en: 'Added' },
  'sb.emotion': { zh: '情绪', en: 'Emotion' },
  'sb.action_en': { zh: '动作(英)', en: 'Action(EN)' },
  'sb.dialogue_en': { zh: '台词(英)', en: 'Dialogue(EN)' },

  // 集数
  'ep.input': { zh: '集数:', en: 'Episode #:' },
  'ep.invalid': { zh: '集数无效', en: 'Invalid episode' },
  'ep.switched': { zh: '已切换到第 {ep} 集', en: 'Switched to episode {ep}' },

  // 通用补充
  'common.id_invalid': { zh: 'ID 格式不合法', en: 'Invalid ID format' },

  // 管线 - 单镜头执行结果
  'wb.shot_done': { zh: '完成', en: 'Done' },
  'wb.shot_skip': { zh: '跳过', en: 'Skipped' },
  'wb.shot_fail': { zh: '失败', en: 'Failed' },
  'wb.shot_err': { zh: '出错', en: 'Error' },
  'wb.shot_timeout': { zh: '超时', en: 'Timeout' },

  // 管线 - 批量完成
  'wb.batch_done': { zh: '✅ 完成', en: '✅ Done' },
  'wb.batch_cancelled': { zh: '⏹ 已取消', en: '⏹ Cancelled' },
  'wb.batch_ok': { zh: '✅', en: '✅' },
  'wb.batch_skip': { zh: '⏭', en: '⏭' },
  'wb.batch_fail': { zh: '❌', en: '❌' },

  // 空状态引导
  'char.empty_hint': { zh: '点击上方按钮创建第一个角色', en: 'Click the button above to create your first character' },
  'scene.empty_hint': { zh: '点击上方按钮创建第一个场景', en: 'Click the button above to create your first scene' },

  // 配乐/字幕
  'wb.gen_music': { zh: '🎵 配乐', en: '🎵 Music' },
  'wb.gen_subtitle': { zh: '📝 字幕', en: '📝 Subtitle' },
  'wb.music_duration': { zh: '时长(秒)', en: 'Duration(s)' },
  'wb.music_mood': { zh: '情绪', en: 'Mood' },
};

// 当前语言（默认中文）
let _lang = localStorage.getItem('drama_lang') || 'zh';

function setLang(lang) {
  _lang = lang;
  localStorage.setItem('drama_lang', lang);
  applyI18n();
}

function applyI18n() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    const entry = I18N[key];
    if (entry) el.textContent = entry[_lang] || entry.zh || key;
  });
}

function t(key, params = {}) {
  const entry = I18N[key];
  let text = entry ? (entry[_lang] || entry.zh || key) : key;
  // 替换参数 {name} → value
  for (const [k, v] of Object.entries(params)) {
    text = text.replace(`{${k}}`, v);
  }
  return text;
}

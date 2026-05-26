# 🔧 代码简洁重构 TODO

> 原则：提取工具函数，消除 if-null / 重复初始化 / 长 if-else 链

---

## ✅ 全部完成

| # | 文件 | 改动 | 状态 |
|---|------|------|------|
| 1 | app.js | `_html()` / `_btnLoad()` 消除 if(el) el.innerHTML 冗余 | ✅ |
| 2 | app.js | `_runTool()` 合并 runPortraits/runPost/runSubtitle | ✅ |
| 3 | app.js | `_runAIGen()` 合并 doAIGenCharacter/doAIGenScene | ✅ |
| 4 | app.js | `_uploadImg()` / `_handleImgDrop()` 合并 ec/es 上传 | ✅ |
| 5 | api.py | `_check_id/_check_uuid/_check_filename/_check_episode/_check_entity_type` | ✅ |
| 6 | api.py | `_active_project_dir()` → `_proj()` 别名统一 | ✅ |
| 7 | tasks.py | `_init_ctx()` / `_cfg_dir()` 提取 | ✅ |
| 8 | tasks.py | `ai_storyboard_task` 用 `_init_ctx` 替代 6 行样板 | ✅ |
| 9 | tasks.py | `_shot_dir` 用 `_cfg_dir` 替换 (T5) | ✅ |
| 10 | tasks.py | `_run_subtitle` 用 `_init_ctx` + `_cfg_dir` 替换 (T4) | ✅ |
| 11 | tasks.py | `tts_single_task` 用 `_init_ctx` 替换 (T3) | ✅ |
| 12 | tasks.py | `music_task` 用 `_init_ctx` 替换 (T2) | ✅ |
| 13 | tasks.py | `ai_characters_task` / `ai_scenes_task` 用 `_init_ctx` + `_cfg_dir` 替换 (T1) | ✅ |
| 14 | tasks.py | `_load_episode_shots` 提取 + preview/produce 统一 (T6) | ✅ |
| 15 | app.js | `_loadEntityPage` 通用列表渲染 (J2) | ✅ |
| 16 | app.js | `_editEntityPanel` 通用编辑面板 (J1) | ✅ |
| 17 | app.js | `_newEntityPanel` 通用新建面板 (J3) | ✅ |
| 18 | api.py | `_parse_entity` 提取 Pydantic 转换 (A2) | ✅ |
| 19 | api.py | `_proj()` mtime 缓存 (A1) | ✅ |

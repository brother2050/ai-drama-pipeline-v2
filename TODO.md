# TODO — 自检发现的问题

> 2026-05-26 逻辑/功能缺陷自检

---

## 🔴 高优先级 — 功能不正确

### 1. 主体库复制路径错误 ✅ 已修复
- **文件**: `web/routers/api.py` — `copy_asset_to_project()` + `add_to_shared_library()`
- **问题**: 复制目标路径是 `_proj() / entity_type`，但实际在 `config/` 下
- **修复**: `_proj() / entity_type` → `_proj() / "config" / entity_type`

### 2. 多剧集状态判断字段不存在 ✅ 已修复
- **文件**: `web/static/js/app.js` — `loadEpisodeManager()`
- **问题**: `has_frame`/`has_video` 字段不存在于 CSV
- **修复**: 改为逐镜头调用 `/shots/{ep}/{sid}/resources` 检查实际资源

---

## 🟡 中优先级 — 体验问题

### 3. 引用计数只检查当前集
- **文件**: `web/static/js/app.js` — `_getRefCounts()`
- **问题**: 只统计当前集（`ep`）的分镜引用，不检查其他集
- **影响**: 角色在第 2 集被引用，但看第 1 集时删除不会提示
- **修复**: 改为遍历所有集的分镜表，或后端提供跨集引用查询 API

### 4. 配置预设不自动保存
- **文件**: `web/static/js/app.js` — `applyPreset()`
- **问题**: 只修改表单值，不触发保存。用户点击预设后需要再点「保存」
- **影响**: 用户可能以为已生效，实际未保存
- **修复**: 预设应用后自动调用 `saveCfg()`，或提示「请点保存」

### 5. 对话编辑不校验返回结构
- **文件**: `web/static/js/app.js` — `sendChatMsg()` + `pipeline/tasks.py` — `ai_chat_edit_task()`
- **问题**: LLM 返回的 shots 直接写入分镜表，不校验字段完整性
- **影响**: LLM 可能返回缺少必要字段（如 shot_id、duration）的分镜
- **修复**: 后端返回前校验每个 shot 必须有 shot_id，前端写入前做基本校验

---

## 🟢 低优先级 — 边缘情况

### 6. 主体库路径依赖项目目录深度 ✅ 已修复
- **文件**: `web/routers/api.py` — `_shared_assets_dir()`
- **修复**: 改用 `ROOT / "shared_assets"` 直接引用

### 7. Worker 状态 API 超时较长 ✅ 已修复
- **文件**: `web/routers/api.py` — `get_worker_status()`
- **修复**: timeout 从 2.0s 减至 0.5s

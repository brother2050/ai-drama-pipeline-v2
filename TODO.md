# TODO — AI 短剧管线 v2 待完善清单

> 按优先级排序：🔴 高 / 🟡 中 / 🟢 低

---

## 🔴 高优先级 — 影响可用性

### 1. 测试覆盖
- [x] 新增 6 项测试: 视频一致性、角色一致性引擎、Pydantic 模型、配置校验、平台兼容性、平台适配参数
- [ ] 缺集成测试（API 端点测试）
- [ ] 缺 Celery 任务测试（mock 模式）
- [ ] 缺前端 E2E 测试

### 2~6. 引擎/编排器 — 已修复 ✅
（上轮已完成）

---

## 🟡 中优先级 — 影响健壮性

### 7. 错误处理 — 已修复 ✅
- [x] Celery 统一错误格式 `format_task_error()`
- [x] 失败回调 `_on_failure` 记录日志

### 8~9. 配置/输入验证 — 已修复 ✅
（上轮已完成）

### 10. 并发安全 — 已修复 ✅
- [x] 前端 `saveShot()` 防抖（500ms）
- [x] 分镜表内联编辑防抖（1000ms 批量保存）
- [x] 前端缓存层减少 API 调用

### 11~13. CLI/Packages/Schemas — 已修复 ✅
（上轮已完成）

---

## 🟢 低优先级 — 影响体验

### 14. 前端体验 — 已修复 ✅
- [x] 分镜表内联编辑表格（直接在表格中编辑场景/角色/动作/台词/运镜/景别/时长）
- [x] 角色管理: 内联编辑弹窗 + 删除按钮
- [x] 场景管理: 内联编辑弹窗 + 删除按钮
- [x] 镜头删除功能（工作台 + 分镜表）
- [x] 资源预览 ESC 键关闭
- [x] 批量执行"取消"按钮
- [x] 移动端响应式布局完善（侧边栏横滑、卡片单列、编辑面板全屏）
- [x] pollTask 最大 300 次轮询限制（约 4 分钟超时）
- [ ] 没有撤销/重做操作

### 15. 日志系统 — 已修复 ✅
- [x] `cli.py` 添加 logger
- [x] `engines/camera.py` 添加 logger
- [x] `engines/emotions.py` 添加 logger
- [x] `infra/text.py` 添加 logger
- [x] `infra/cache.py` 添加 logger
- [x] `scripts/project_mgr.py` 添加 logger
- [x] `web/services/__init__.py` 统一日志配置服务
- [ ] 没有日志文件输出（可通过 setup_logging(log_file=...) 启用）

### 16. 文档 — 已修复 ✅
（上轮已完成）

### 17. `infra/transitions.py` — 已修复 ✅
- [x] 多段视频 xfade offset 精确计算（累积时长 - 转场重叠）
- [x] 音频使用 acrossfade 与视频 xfade 时间同步
- [x] 添加 `-movflags +faststart` 优化流媒体播放

### 18~19. 横转竖/分发 — 已修复 ✅
（上轮已完成）

### 20. 安全加固 — 已修复 ✅
- [x] 简易 Rate Limiting（滑动窗口，60s/120 次）
- [x] API 路径遍历防护（上轮已完成）
- [x] 角色/场景删除 API（DELETE 端点）
- [ ] `POST /api/config` 没有鉴权（需要用户系统，暂不做）
- [ ] Celery 任务没有用户隔离（需要用户系统，暂不做）

### 21. 性能优化 — 已修复 ✅
- [x] 前端缓存层（`cachedFetch` + `invalidateCache`，30s TTL）
- [x] 系统状态缓存（10s TTL，避免频繁刷新）
- [ ] `api/__init__.py` 懒加载（影响小，暂不做）

### 22. 国际化
- [ ] 前端硬编码中文
- [ ] 错误信息中英文混杂

---

## 📋 已完成（记录）

- [x] 数据库 SQLite/PostgreSQL 双模式兼容
- [x] 缺失 `infra/transitions.py` 补全
- [x] `web/app.py` Path 导入修复
- [x] `post/production.py` 视频路径修复
- [x] `engines/workflow_builder.py` 安全检查
- [x] `pyproject.toml` build-backend 修复
- [x] Celery + Redis 统一异步方案
- [x] 每步独立执行（缺工具跳过不阻塞）
- [x] 人性化工作台（批量+单个调整+资源预览）
- [x] 工具状态检测 API
- [x] 23 项基础测试
- [x] **pyproject.toml entry point 修复**
- [x] **pyproject.toml packages 补全**
- [x] **engines/consistency.py 真实实现**
- [x] **engines/video_consistency.py 真实实现**
- [x] **flow/orchestrator.py 标记废弃**
- [x] **flow/batch.py 标记废弃**
- [x] **engines/_portrait_helper.py 标记废弃**
- [x] **pipeline/tasks.py 超时控制**
- [x] **web/schemas Pydantic 模型**
- [x] **API 输入校验**
- [x] **路径遍历防护**
- [x] **Config 配置校验**
- [x] **infra/retry.py 集成**
- [x] **post/vertical.py 人脸检测**
- [x] **post/distributor.py 平台检查**
- [x] **README 更新**
- [x] **Celery 统一错误格式** (`format_task_error` + `_on_failure` 回调)
- [x] **前端防抖** (saveShot 500ms, 分镜表 1000ms)
- [x] **前端缓存层** (`cachedFetch` + `invalidateCache`)
- [x] **分镜表内联编辑表格**
- [x] **角色/场景内联编辑 + 删除 API**
- [x] **镜头删除功能**
- [x] **ESC 关闭浮层**
- [x] **批量执行取消按钮**
- [x] **pollTask 超时限制** (300 次)
- [x] **移动端响应式布局**
- [x] **日志系统** (6 个模块添加 logger + 统一配置服务)
- [x] **Rate Limiting** (滑动窗口 60s/120 次)
- [x] **转场 offset 精确计算** (多段 xfade + acrossfade 同步)
- [x] **测试扩充** (29 项，新增 6 项)

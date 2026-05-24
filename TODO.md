# TODO — AI 短剧管线 v2 待完善清单

> 按优先级排序：🔴 高 / 🟡 中 / 🟢 低

---

## 🔴 高优先级 — 影响可用性

### 1. 测试覆盖不足
- [ ] 只有 `tests/test_all.py` 一个文件，23 个测试
- [ ] 缺少集成测试（API 端点测试）
- [ ] 缺少 Celery 任务测试（mock 模式）
- [ ] 缺少前端 E2E 测试
- [ ] `engines/` 模块缺少单元测试（workflow_builder, consistency 等）
- [ ] `post/` 模块缺少测试（production, vertical 等实际调用 ffmpeg）
- [ ] `infra/database/` 缺少 PostgreSQL 模式测试

### 2. `engines/consistency.py` — placeholder 实现
- [ ] `prepare_embedding()` 只写 JSON 文件，没有实际嵌入
- [ ] `verify_consistency()` 返回固定 0.8，没有真实比对
- [ ] 需要接入 face_recognition / insightface 做真实人脸一致性检测

### 3. `engines/video_consistency.py` — placeholder 实现
- [ ] `check_video_consistency()` 返回固定结果
- [ ] 需要实际的视频帧人脸比对

### 4. `flow/orchestrator.py` — 编排器未被使用
- [ ] `ShotOrchestrator` 定义了完整流程但从未被调用
- [ ] 与 `pipeline/tasks.py` 中的 `shot_task` 功能重复
- [ ] 应该统一为一套，删除冗余

### 5. `flow/batch.py` — 批量调度未被使用
- [ ] `batch_run()` 有 ThreadPoolExecutor 实现但从未调用
- [ ] 前端的批量操作是逐个串行调用 API
- [ ] 应该让 Celery 支持批量任务编排

### 6. `engines/_portrait_helper.py` — 未被引用
- [ ] `ensure_reference_images()` 函数没有任何模块引用
- [ ] 与 `engines/portrait.py` 功能重叠
- [ ] 应该合并或删除

---

## 🟡 中优先级 — 影响健壮性

### 7. 错误处理不完善
- [ ] `pipeline/tasks.py` 中 `step_fn.apply().get()` 没有超时控制
- [ ] 后端 API 调用（httpx）没有统一的重试机制（`infra/retry.py` 存在但未被后端使用）
- [ ] Celery 任务内部异常没有统一的错误报告格式
- [ ] 前端 `pollTask()` 没有最大轮询次数限制（可能无限等待）

### 8. 配置验证缺失
- [ ] `Config` 类加载配置后没有验证必填字段
- [ ] `project.yaml` 可以写入任意无效值
- [ ] 缺少 schema 验证（如 pydantic model）

### 9. 输入验证不足
- [ ] `POST /api/storyboard/{episode}` 接受任意 dict，没有验证字段
- [ ] `POST /api/characters` 只验证 id 非空
- [ ] `POST /api/config` 直接写入 YAML，没有验证
- [ ] `StepRequest` 只验证 episode + shot_id，不验证 shot_id 格式

### 10. 并发安全
- [ ] `saveShot()` 前端可以快速连续点击，没有防抖
- [ ] 同一镜头同时执行多个步骤（如 TTS + 首帧）可能产生文件冲突
- [ ] `infra/config.py` 的 `_cache` 有锁但 `load_config` 无锁路径存在 TOCTOU 竞态

### 11. `cli.py` 入口注册问题
- [ ] `pyproject.toml` 注册 `drama = "cli:main"` 但 `cli.py` 的函数叫 `cli` 不是 `main`
- [ ] `pip install -e .` 后 `drama` 命令会报错
- [ ] 需要改为 `drama = "cli:cli"` 或在 cli.py 中添加 `main = cli`

### 12. `web/services/` 和 `web/schemas/` 空目录
- [ ] 有 `__init__.py` 但无内容，应该删除或实现
- [ ] `schemas/` 应该放 Pydantic 模型（目前散在 api.py 中）

### 13. pyproject.toml packages 配置
- [ ] `include = ["api*", "infra*", "pipeline*", "post*", "web*", "cli*"]`
- [ ] 缺少 `engines*`, `flow*`, `scripts*`, `tests*`
- [ ] `pip install` 后这些模块不会被安装

---

## 🟢 低优先级 — 影响体验

### 14. 前端体验
- [ ] 分镜表编辑只能逐个 prompt() 输入，应该有内联编辑表格
- [ ] 角色/场景编辑只有"编辑功能开发中"提示
- [ ] 没有删除镜头/角色/场景的功能
- [ ] 没有撤销/重做操作
- [ ] 资源预览不支持键盘操作（ESC 关闭等）
- [ ] 批量执行没有"取消"按钮
- [ ] 移动端响应式布局不完善

### 15. 日志系统
- [ ] 多个模块缺少 logger（camera, emotions, text, cache, database/*, scripts, cli）
- [ ] 没有统一的日志格式/级别配置
- [ ] 没有日志文件输出（`logs/` 目录在 .gitignore 但未创建）
- [ ] Celery Worker 日志和 Web 日志没有分离

### 16. 文档
- [ ] README 中 `pip install -e .` 的安装方式因 pyproject.toml 问题可能失败
- [ ] 缺少 API 文档（FastAPI 自动生成 /docs 但未在 README 提及）
- [ ] 缺少配置字段说明文档
- [ ] 缺少角色/场景 YAML 格式说明
- [ ] 缺少 ComfyUI 工作流模板说明

### 17. `infra/transitions.py` — 转场实现简化
- [ ] 多段视频的 xfade 滤镜链 offset 计算可能不精确
- [ ] 音频 amix 和视频 xfade 的时间轴可能不同步
- [ ] 需要更严格的测试

### 18. `post/vertical.py` — 横转竖实现
- [ ] `face_track` 模式实际是 blur_bg，没有真正的人脸追踪
- [ ] 需要接入 face detection 做真正的面部居中裁剪

### 19. `post/distributor.py` — 分发是空壳
- [ ] `distribute()` 只返回配置信息，没有实际上传功能
- [ ] 需要对接各平台 API 或至少生成平台适配参数

### 20. 安全加固
- [ ] `POST /api/config` 任何人都能修改配置，没有鉴权
- [ ] `POST /api/projects/new` 可以创建任意项目名（路径注入风险）
- [ ] `GET /api/files/` 路径遍历风险（`../` 攻击）
- [ ] Celery 任务没有用户隔离
- [ ] 缺少 rate limiting

### 21. 性能优化
- [ ] `loadResources()` 每个镜头独立 API 调用，应该批量查询
- [ ] `renderShotsGrid()` 对每个镜头都调 `loadResources()`，N 个镜头 = N 次 API
- [ ] 前端没有缓存，每次切页面都重新加载
- [ ] `api/__init__.py` 导入所有后端模块，启动时全部注册（应改为懒加载）

### 22. 国际化
- [ ] 前端硬编码中文
- [ ] 错误信息中英文混杂
- [ ] 配置文件字段名英文、值中文，不统一

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

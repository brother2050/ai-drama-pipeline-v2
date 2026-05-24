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

### 2. `engines/consistency.py` — 已改进 ✅
- [x] `prepare_embedding()` 现在提取真实人脸嵌入（insightface/face_recognition/哈希回退）
- [x] `verify_consistency()` 使用余弦相似度进行真实比对
- [x] 支持 insightface、face_recognition、图片哈希三级回退

### 3. `engines/video_consistency.py` — 已改进 ✅
- [x] `check_video_consistency()` 抽取关键帧进行人脸比对
- [x] 支持 insightface/face_recognition/哈希三级回退
- [x] 自动清理临时帧文件

### 4. `flow/orchestrator.py` — 已标记废弃 ✅
- [x] 添加 deprecation 警告，建议使用 `pipeline.tasks.shot_task`
- [x] 保留代码仅为向后兼容

### 5. `flow/batch.py` — 已标记废弃 ✅
- [x] 添加 deprecation 警告，建议使用 `pipeline.tasks.preview_task`
- [x] 保留代码仅为向后兼容

### 6. `engines/_portrait_helper.py` — 已标记废弃 ✅
- [x] 添加 deprecation 警告，建议使用 `engines.portrait.ensure_portrait()`
- [x] 失败时委托给 `engines.portrait`

---

## 🟡 中优先级 — 影响健壮性

### 7. 错误处理 — 已改进 ✅
- [x] `pipeline/tasks.py` 中 `step_fn.apply().get()` 添加了超时控制（120~600s）
- [x] `web/routers/api.py` 使用 `infra/retry.py` 做工具检测重试
- [ ] Celery 任务内部异常没有统一的错误报告格式
- [ ] 前端 `pollTask()` 没有最大轮询次数限制（可能无限等待）

### 8. 配置验证 — 已实现 ✅
- [x] `Config` 类添加 `_validate()` 方法，检查必填字段和数值范围
- [x] 校验分辨率格式、端口范围、超时范围
- [x] 不阻断启动，仅记录警告日志
- [ ] 缺少 pydantic schema 验证（如需要可扩展）

### 9. 输入验证 — 已实现 ✅
- [x] 创建 `web/schemas/__init__.py`，定义所有 Pydantic 请求模型
- [x] `StepRequest` 校验 episode >= 1，shot_id 格式
- [x] `CharacterData` / `SceneData` 校验 ID 格式（防注入）
- [x] `TTSRequest` 校验文本长度、emotion/language 格式
- [x] `PipelineRequest` 校验 command/level 枚举值
- [x] 分镜保存校验 shot_id 格式

### 10. 并发安全
- [ ] `saveShot()` 前端可以快速点击，没有防抖
- [ ] 同一镜头同时执行多个步骤可能产生文件冲突
- [x] `infra/config.py` 的 `_cache` 有锁保护

### 11. `cli.py` 入口注册 — 已修复 ✅
- [x] `pyproject.toml` 改为 `drama = "cli:cli"`
- [x] `pip install -e .` 后 `drama` 命令正常工作

### 12. `web/schemas/` 空目录 — 已实现 ✅
- [x] 创建完整的 Pydantic 数据模型
- [ ] `web/services/` 仍为空目录

### 13. pyproject.toml packages — 已修复 ✅
- [x] 添加 `engines*`, `flow*`, `scripts*` 到 include 列表

---

## 🟢 低优先级 — 影响体验

### 14. 前端体验
- [ ] 分镜表编辑只能逐个 prompt() 输入
- [ ] 角色/场景编辑只有"编辑功能开发中"提示
- [ ] 没有删除镜头/角色/场景的功能
- [ ] 没有撤销/重做操作
- [ ] 资源预览不支持键盘操作（ESC 关闭等）
- [ ] 批量执行没有"取消"按钮
- [ ] 移动端响应式布局不完善

### 15. 日志系统
- [ ] 多个模块缺少 logger（camera, emotions, text, cache, database/*, scripts, cli）
- [ ] 没有统一的日志格式/级别配置
- [ ] 没有日志文件输出
- [ ] Celery Worker 日志和 Web 日志没有分离

### 16. 文档 — 已改进 ✅
- [x] README 中 `pip install -e .` 的安装说明已更新
- [x] 添加了 API 文档访问地址（Swagger UI / ReDoc）
- [ ] 缺少配置字段说明文档
- [ ] 缺少角色/场景 YAML 格式说明
- [ ] 缺少 ComfyUI 工作流模板说明

### 17. `infra/transitions.py` — 转场实现
- [ ] 多段视频的 xfade 滤镜链 offset 计算可能不精确
- [ ] 音频 amix 和视频 xfade 的时间轴可能不同步

### 18. `post/vertical.py` — 已改进 ✅
- [x] `face_track` 模式尝试使用 face_recognition 做真正人脸检测
- [x] 检测到人脸时以人脸中心做裁剪
- [x] 未检测到人脸时回退到 blur_bg 模式

### 19. `post/distributor.py` — 已改进 ✅
- [x] 添加平台兼容性检查 `check_platform_compat()`
- [x] 添加适配参数生成 `get_adapt_params()`
- [x] 添加视频信息获取 `get_video_info()`
- [ ] 实际上传功能需要对接各平台 API

### 20. 安全加固
- [x] API 路径遍历防护（`_safe_path()` 函数）
- [x] 任务 ID 格式校验（UUID 格式）
- [x] 角色/场景 ID 格式校验（防注入）
- [ ] `POST /api/config` 没有鉴权
- [ ] Celery 任务没有用户隔离
- [ ] 缺少 rate limiting

### 21. 性能优化
- [ ] `loadResources()` 每个镜头独立 API 调用
- [ ] 前端没有缓存
- [ ] `api/__init__.py` 导入所有后端模块

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
- [x] **pyproject.toml entry point 修复** (`cli:main` → `cli:cli`)
- [x] **pyproject.toml packages 补全** (添加 engines, flow, scripts)
- [x] **engines/consistency.py 真实实现** (insightface/face_recognition/哈希三级回退)
- [x] **engines/video_consistency.py 真实实现** (关键帧抽取+人脸比对)
- [x] **flow/orchestrator.py 标记废弃** (建议使用 pipeline.tasks.shot_task)
- [x] **flow/batch.py 标记废弃** (建议使用 pipeline.tasks.preview_task)
- [x] **engines/_portrait_helper.py 标记废弃** (委托给 engines.portrait)
- [x] **pipeline/tasks.py 超时控制** (apply().get() 添加 timeout)
- [x] **web/schemas Pydantic 模型** (所有 API 请求模型)
- [x] **API 输入校验** (episode, shot_id, character_id, scene_id 格式)
- [x] **路径遍历防护** (_safe_path 函数)
- [x] **Config 配置校验** (必填字段, 数值范围, 分辨率格式)
- [x] **infra/retry.py 集成** (工具检测使用重试机制)
- [x] **post/vertical.py 人脸检测** (face_track 模式真正检测人脸)
- [x] **post/distributor.py 平台检查** (兼容性检查+适配参数)
- [x] **README 更新** (安装说明+API 文档链接)

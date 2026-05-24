# 🔍 代码逻辑审查报告

> 审查时间: 2026-05-24
> 审查范围: 全项目源码

---

## 🔴 高优先级 — 影响运行正确性

### 1. Celery task_routes 名称不匹配
**文件**: `pipeline/celery_app.py`
**问题**: `task_routes` 中定义的路由名称是 `"pipeline.tts"`, `"pipeline.first_frame"` 等，但实际任务名称是 `"pipeline.step.tts"`, `"pipeline.step.first_frame"` 等。
**影响**: 任务路由规则全部失效，所有任务都会走默认队列。
**修复**: 更新 `task_routes` 为实际任务名称，或去掉 step_ 前缀。

### 2. `post_task` 调用缺少 `vertical` 参数
**文件**: `pipeline/tasks.py` → `produce_task()`
**问题**: `produce_task` 调用 `post_task.apply(args=[config_path, episode])` 时没有传递 `vertical` 参数，但 `post_task` 签名是 `post_task(self, config_path, episode, vertical=False)`。
**影响**: 通过 `produce_task` 执行的后期合成永远无法横转竖。

### 3. `pipeline/preview.py` 中视频生成逻辑缺失
**文件**: `pipeline/preview.py` → `_process_shot()`
**问题**: 视频生成部分只有一行 `logger.info(f"⚠ 视频生成需要 ComfyUI 工作流模板")`，没有实际调用 `WorkflowBuilder`。
**影响**: preview 命令永远不会生成视频。

### 4. `step_first_frame` 未使用 `WorkflowBuilder.build_first_frame()`
**文件**: `pipeline/tasks.py` → `step_first_frame()`
**问题**: 任务手动构建 prompt，但没有使用 `WorkflowBuilder.build_first_frame()` 方法（该方法已经处理了 IP-Adapter 注入、多角色链式参考图等复杂逻辑）。
**影响**: 首帧生成跳过了角色一致性注入、多角色同框等核心功能。

### 5. `shot_task` 中 `.apply()` 导致进度不可见
**文件**: `pipeline/tasks.py` → `shot_task()`
**问题**: 使用 `.apply()` 在当前进程同步执行子任务，但子任务的 `self.update_state()` 在 eager 模式下不会传播到前端。
**影响**: 前端轮询 `GET /api/tasks/{id}` 时看不到子步骤进度，只能看到 shot 级别的进度。

### 6. `post/production.py` 拼接后未生成 `final.mp4`
**文件**: `post/production.py`
**问题**: 拼接后的文件名是 `episode_XX_concat.mp4` 或 `episode_XX_subtitled.mp4`，但 `flow/episode.py` 的 `get_episode_status()` 检查的是 `final.mp4`。
**影响**: 集状态查询永远显示 "未完成"。

---

## 🟡 中优先级 — 影响健壮性

### 7. 数据库模块完全未被使用
**文件**: `infra/database/` 全模块
**问题**: 完整的 CRUD 操作（characters, scenes, episodes, shots）已实现，但整个管线都直接读 CSV/YAML 文件，数据库从未被调用。
**影响**: 浪费代码；generation_status 表无法追踪生成进度；无法利用事务保证一致性。

### 8. `post/vertical.py` 与 `infra/ffmpeg.py` 功能重复
**问题**: 两个模块都有 `to_vertical()` 函数，但 `post/vertical.py` 支持人脸检测裁剪，`infra/ffmpeg.py` 只有模糊背景模式。`post/production.py` 调用的是 `infra/ffmpeg.py` 版本。
**影响**: 横转竖丢失了人脸追踪能力。

### 9. `post/transitions.py` 与 `infra/transitions.py` 重复
**问题**: `post/transitions.py` 只有字典映射和 `get_xfade_filter()` 函数，`infra/transitions.py` 有完整实现。两者定义了相同的 `TRANSITIONS` 字典。
**影响**: 维护混乱，修改转场时容易遗漏。

### 10. `pipeline/preview.py` 和 `pipeline/producer.py` 与 Celery 任务逻辑重复
**问题**: 这两个独立脚本与 `pipeline/tasks.py` 中的 `preview_task` / `produce_task` 功能完全重复，但实现细节有差异（如 preview.py 缺少视频生成）。
**影响**: 维护负担，bug 修复需要改两处。

### 11. `engines/_portrait_helper.py` 废弃模块未清理
**问题**: 标记为废弃，已被 `engines/portrait.py` 替代，但仍保留在代码库中。
**影响**: 代码混乱。

### 12. `infra/transitions.py` 中 `_get_audio_duration()` 未被使用
**问题**: 定义了但从未被调用。
**影响**: 死代码。

### 13. `ConfigUpdate` schema 未被使用
**文件**: `web/schemas/__init__.py`
**问题**: 定义了 `ConfigUpdate` 类，但 `POST /api/config` 路由直接使用 `dict` 类型。
**影响**: 配置更新接口缺少 Pydantic 校验。

---

## 🟢 低优先级 — 影响体验/可维护性

### 14. 缺少 `config/models_registry.yaml`
**问题**: `flow/model_registry.py` 引用此文件，但不存在，回退到内置默认值。
**影响**: 无法通过 YAML 配置自定义模型参数。

### 15. 缺少 `workflows/` 目录
**问题**: `WorkflowBuilder` 期望工作流 JSON 模板在此目录，但目录不存在。
**影响**: ComfyUI 工作流模板需要用户自行创建。

### 16. `storyboard/episodes.csv` 数据不足
**问题**: 只有一行示例数据。
**影响**: 需要用户自行编写分镜表。

### 17. `config/project.yaml` 被 .gitignore 忽略
**问题**: 实际配置文件不进版本控制（正确做法），但新克隆后需要从 `.example` 复制。

### 18. `generate_srt` 字幕时间轴不精确
**文件**: `post/subtitle.py`
**问题**: 字幕时间使用固定 `duration` 累加，没有考虑转场重叠时间。
**影响**: 长视频中字幕会逐渐偏移。

---

## 📋 总结

| 类别 | 数量 |
|------|------|
| 🔴 高优先级 | 6 |
| 🟡 中优先级 | 7 |
| 🟢 低优先级 | 5 |
| **合计** | **18** |

最紧迫的修复项: #1 (task_routes), #2 (vertical 参数), #3 (preview 视频生成), #4 (首帧 IP-Adapter), #6 (final.mp4 命名)。

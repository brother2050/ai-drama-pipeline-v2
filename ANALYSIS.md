# 🔍 代码逻辑审查报告

> 审查时间: 2026-05-24
> 审查范围: 全项目源码

---

## ✅ 已修复

### 🔴 高优先级

| # | 问题 | 状态 |
|---|------|------|
| 1 | Celery task_routes 名称不匹配 (`pipeline.tts` vs `pipeline.step.tts`) | ✅ 已修正 |
| 2 | `produce_task` 调 `post_task` 漏传 `vertical` 参数 | ✅ 已修正 |
| 3 | `preview.py` 视频生成是空壳 | ✅ 补全 WorkflowBuilder 调用 |
| 4 | `step_first_frame` 绕过 `WorkflowBuilder.build_first_frame()` | ✅ 抽取 `_run_first_frame` 使用 WorkflowBuilder |
| 5 | `shot_task` 用 `.apply()` 导致子步骤进度不可见 | ✅ 重构为直接调用 `_run_*` 函数 |
| 6 | 拼接后文件名不一致 (`concat.mp4` vs `final.mp4`) | ✅ 输出 `episode_XX_final.mp4` |

### 🟡 中优先级

| # | 问题 | 状态 |
|---|------|------|
| 7 | 数据库模块未被使用 | ⏳ 保留（CSV 方式可用，后续集成） |
| 8 | `post/vertical.py` 人脸追踪未被 production.py 使用 | ✅ production.py 改用 `post.vertical.to_vertical` |
| 9 | `post/transitions.py` 与 `infra/transitions.py` 重复 | ✅ 删除 `post/transitions.py` |
| 10 | `preview.py`/`producer.py` 与 Celery tasks 逻辑重复 | ✅ preview/producer 也改用 WorkflowBuilder |
| 11 | `_portrait_helper.py` 废弃未删 | ✅ 已删除 |
| 12 | `_get_audio_duration()` 死代码 | ✅ 已移除 |
| 13 | `ConfigUpdate` schema 定义了但没用 | ✅ `POST /api/config` 改用 Pydantic 校验 |

### 额外修复

- `PipelineRequest` schema 增加 `vertical` 字段
- `web/routers/api.py` pipeline/run 传递 `vertical` 给 produce/post
- `cli.py` `all` 命令支持 `--vertical` 选项
- `flow/episode.py` 检查 `*_final.mp4` 文件名
- `pipeline/producer.py` 首帧改用 WorkflowBuilder（含 IP-Adapter）

---

## ⏳ 待完善

| # | 优先级 | 问题 |
|---|--------|------|
| 7 | 🟡 | 数据库模块集成（已有完整 CRUD，管线未调用） |
| 14 | 🟢 | 缺少 `config/models_registry.yaml`（回退内置默认值） |
| 15 | 🟢 | 缺少 `workflows/` 目录（ComfyUI 模板需用户创建） |
| 16 | 🟢 | `storyboard/episodes.csv` 示例数据不足 |
| 17 | 🟢 | 字幕时间轴未考虑转场重叠 |
| 18 | 🟢 | `post/transitions.py` 已删除，`post/__init__.py` 可能需要更新 |

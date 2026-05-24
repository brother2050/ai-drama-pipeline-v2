# 🔍 代码逻辑审查报告

> 审查时间: 2026-05-24
> 审查范围: 全项目源码

---

## ✅ 全部已修复

### 🔴 高优先级

| # | 问题 | 修复 |
|---|------|------|
| 1 | Celery task_routes 名称不匹配 | ✅ 修正为 `pipeline.step.*`，补全 12 条路由 |
| 2 | `produce_task` 漏传 `vertical` | ✅ `produce_task(config, episode, vertical)` |
| 3 | `preview.py` 视频生成空壳 | ✅ 补全 WorkflowBuilder 调用 |
| 4 | 首帧绕过 IP-Adapter | ✅ 抽取 `_run_first_frame` 使用 `build_first_frame()` |
| 5 | `shot_task` 子步骤进度不可见 | ✅ 直接调用 `_run_*` 函数，`update_state` 实时传播 |
| 6 | `final.mp4` 命名不一致 | ✅ 输出 `episode_XX_final.mp4`，episode.py 匹配新文件名 |

### 🟡 中优先级

| # | 问题 | 修复 |
|---|------|------|
| 7 | 数据库模块未集成 | ✅ 新增 `generation.py` CRUD，`shot_task` 写入 generation_status |
| 8 | 人脸追踪未被使用 | ✅ production.py 改用 `post.vertical.to_vertical` |
| 9 | 转场模块重复 | ✅ 删除 `post/transitions.py`，统一用 `infra/transitions` |
| 10 | preview/producer 逻辑重复 | ✅ 改用 WorkflowBuilder（含 IP-Adapter） |
| 11 | `_portrait_helper.py` 废弃 | ✅ 已删除 |
| 12 | `_get_audio_duration` 死代码 | ✅ 已移除 |
| 13 | `ConfigUpdate` 未使用 | ✅ `POST /api/config` 改用 Pydantic 校验 |

### 🟢 低优先级

| # | 问题 | 修复 |
|---|------|------|
| 14 | 缺 `models_registry.yaml` | ✅ 创建，含 sd15/flux/animatediff/cogvideox + GPU profiles |
| 15 | 缺 `workflows/` 目录 | ✅ 创建，含 README 说明工作流模板获取方式 |
| 16 | 分镜表数据不足 | ✅ 补充到 8 镜头（含多角色同框、情绪变化） |
| 17 | 字幕时间轴偏移 | ✅ `generate_srt` 增加 `transition_duration` 参数修正 |
| 18 | 废弃模块未清理 | ✅ 删除 `flow/orchestrator.py`、`flow/batch.py` |

### 额外修复

- `PipelineRequest` 增加 `vertical` 字段
- `web/routers/api.py` pipeline/run 传递 vertical
- `cli.py` `all` 命令支持 `--vertical`
- `engines/__init__.py` 导出核心类
- `ShotManager` 传入实际 storyboard 路径（不再用空字符串）
- `infra/database/__init__.py` 导出 generation 模块
- `flow/episode.py` 查询数据库补充状态详情

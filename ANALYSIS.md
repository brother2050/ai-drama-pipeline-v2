# 🔍 代码逻辑审查报告

> 审查时间: 2026-05-24
> 审查范围: 全项目源码（二轮）

---

## ✅ 全部已修复

### 第一轮（18项）

| # | 优先级 | 问题 | 修复 |
|---|--------|------|------|
| 1 | 🔴 | Celery task_routes 名称不匹配 | ✅ |
| 2 | 🔴 | produce_task 漏传 vertical | ✅ |
| 3 | 🔴 | preview.py 视频生成空壳 | ✅ |
| 4 | 🔴 | 首帧绕过 IP-Adapter | ✅ |
| 5 | 🔴 | shot_task 子步骤进度不可见 | ✅ |
| 6 | 🔴 | final.mp4 命名不一致 | ✅ |
| 7 | 🟡 | 数据库模块未集成 | ✅ |
| 8 | 🟡 | 人脸追踪未被使用 | ✅ |
| 9 | 🟡 | 转场模块重复 | ✅ |
| 10 | 🟡 | preview/producer 逻辑重复 | ✅ |
| 11 | 🟡 | _portrait_helper.py 废弃 | ✅ |
| 12 | 🟡 | _get_audio_duration 死代码 | ✅ |
| 13 | 🟡 | ConfigUpdate schema 未使用 | ✅ |
| 14 | 🟢 | 缺 models_registry.yaml | ✅ |
| 15 | 🟢 | 缺 workflows/ 目录 | ✅ |
| 16 | 🟢 | 分镜表数据不足 | ✅ |
| 17 | 🟢 | 字幕时间轴偏移 | ✅ |
| 18 | 🟢 | 废弃模块未清理 | ✅ |

### 第二轮（5项）

| # | 优先级 | 问题 | 修复 |
|---|--------|------|------|
| 19 | 🔴 | 前端 saveCfg 发送格式 vs ConfigUpdate schema 不兼容 | ✅ API 改为接受 raw dict |
| 20 | 🔴 | test_update_config 测试用例格式错误 | ✅ 补充新格式测试 |
| 21 | 🟡 | producer.py WorkflowBuilder 缺 comfyui 参数 | ✅ 3处补齐 |
| 22 | 🟡 | preview.py WorkflowBuilder 缺 comfyui 参数 | ✅ 2处补齐 |
| 23 | 🟢 | ConfigUpdate import 未使用 | ✅ 清理 |

# 🔍 代码逻辑审查报告

> 审查时间: 2026-05-24
> 审查范围: 全项目源码（四轮）

---

## ✅ 全部已修复（四轮合计 35 项）

### 第一轮（18项）— 逻辑 & 架构
task_routes、vertical 传递、preview 视频、首帧 IP-Adapter、shot_task 进度、final.mp4、DB 集成、人脸追踪、转场合并、废弃模块、字幕时间轴、models_registry、workflows 目录等

### 第二轮（5项）— API & 一致性
config API 格式兼容、test 修正、WorkflowBuilder comfyui 参数

### 第三轮（8项）— 深度质量
_ensure_registered 竞态、Celery task_failure 信号、中间文件清理、异常写 DB、全局异常处理、FFmpeg list 清理、Image.open context manager

### 第四轮（4项）— 安全 & 健壮性

| # | 问题 | 修复 |
|---|------|------|
| 32 | Rate limit 定义了但从未调用 | ✅ 添加为 router 级 dependency |
| 33 | Rate limit 内存泄露 | ✅ 超 1000 IP 时自动清理过期 |
| 34 | 前端 XSS (e.message in innerHTML) | ✅ 添加 esc() 转义函数 |
| 35 | addShot ID 冲突 | ✅ 找最大 ID 而非用 count |

---

## ⏳ 已知限制（非 bug，设计取舍）

| 项目 | 说明 | 影响 |
|------|------|------|
| API 无分页 | 小项目可接受 | 低 |
| 前端 shot_id/value 未全量转义 | 数据来自 API（受控） | 低 |
| Container 全局单例未初始化 | 每次请求/任务按需创建 | 无 |
| 删除角色不更新 storyboard | 用户手动管理引用 | 低 |
| CSV int 比较 | FastAPI 已转 int，CSV 存 str | 无 |
| config 更新不重载 Container | 下次创建时读新配置 | 无 |

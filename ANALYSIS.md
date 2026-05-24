# 🔍 代码逻辑审查报告

> 审查时间: 2026-05-24
> 审查范围: 全项目源码（逐文件）

---

## ✅ 全部已修复（五轮合计 47 项）

### 第一轮（18项）— 逻辑 & 架构
task_routes、vertical 传递、preview 视频、首帧 IP-Adapter、shot_task 进度、final.mp4、DB 集成、人脸追踪、转场合并、废弃模块、字幕时间轴、models_registry、workflows 目录等

### 第二轮（5项）— API & 一致性
config API 格式兼容、test 修正、WorkflowBuilder comfyui 参数

### 第三轮（8项）— 深度质量
_ensure_registered 竞态、Celery task_failure 信号、中间文件清理、异常写 DB、全局异常处理、FFmpeg list 清理、Image.open context manager

### 第四轮（4项）— 安全 & 健壮性
Rate limit 定义了但从未调用、Rate limit 内存泄露、前端 XSS、addShot ID 冲突

### 第五轮（12项）— 逻辑缺失修复

| # | 问题 | 修复 |
|---|------|------|
| 36 | Workflow JSON 模板文件缺失（管线不可用） | ✅ 创建 4 个示例工作流模板 |
| 37 | ComfyUI 缺少 upload_image 方法（参考图无法上传） | ✅ 添加 upload_image + 正确调用 |
| 38 | translate_to_english 无 LLM 支持（中文 prompt 不翻译） | ✅ tasks.py / preview.py 传入 LLM |
| 39 | Container._backend_config 中 _project_dir 永远为空 | ✅ Config.__init__ 和 reload 注入 |
| 40 | CSV/schema 缺少 action_en/dialogue_en 列 | ✅ CSV + schema + shots.py 补全 |
| 41 | cli.py produce 错误传入 vertical 参数 | ✅ produce 不传 vertical |
| 42 | save_storyboard 未同步数据库 | ✅ 写 CSV 后同步 shots 表 |
| 43 | workflow_builder prompt 构建与 prompt.py 重复 | ✅ 复用 build_prompt 函数 |
| 44 | MusicGenerator 与 TemplateMusic 功能重复 | ✅ 通过 Container 获取后端 |
| 45 | SadTalker 后端注册但配置无对应条目 | ✅ 配置增加 sadtalker + wav2lip |
| 46 | 中间文件清理可能误删活跃文件 | ✅ 增加 concat_out 保护 |
| 47 | infra/http.py ApiClient 未被使用 | ✅ 标注为共享工具 |

### 第六轮（7项）— 深度逻辑修复

| # | 问题 | 修复 |
|---|------|------|
| 48 | ensure_portrait 传 None container（自动定妆照永远不生成） | ✅ 传入 _SimpleContainer(comfyui) |
| 49 | ensure_portrait 的 workflow 格式错误（非 ComfyUI API 格式） | ✅ 改用 WorkflowBuilder 构建 |
| 50 | run_post 完成后不更新集状态到数据库 | ✅ 写入 episodes 表 |
| 51 | _run_tts/_run_lipsync/_run_video 不包裹异常 | ✅ try/except 返回 error dict |
| 52 | shot_task 不记录每步耗时 | ✅ time.time() 计时 + elapsed 字段 |
| 53 | save_character/save_scene 不同步数据库 | ✅ YAML + DB 双写 |
| 54 | delete_character/delete_scene 不同步数据库 | ✅ 文件 + DB 双删 |

---

## 🟡 已知限制（非 bug，设计取舍）

| 项目 | 说明 | 影响 |
|------|------|------|
| API 无分页 | 小项目可接受 | 低 |
| 前端 shot_id/value 未全量转义 | 数据来自 API（受控） | 低 |
| Container 全局单例未初始化 | 每次请求/任务按需创建 | 无 |
| 删除角色不更新 storyboard | 用户手动管理引用 | 低 |
| CSV int 比较 | FastAPI 已转 int，CSV 存 str | 无 |
| config 更新不重载 Container | 下次创建时读新配置 | 无 |

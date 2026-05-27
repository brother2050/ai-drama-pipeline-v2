# TODO — 待开发功能

> 更新：2026-05-27

---

## 🔴 待开发

（暂无）

---

## ✅ 已完成

### 2026-05-27 outfit 图片批量/单独生成
- 新增 `POST /characters/{char_id}/generate-outfit?outfit_key=xxx` 单独生成接口
- 新增 `POST /characters/{char_id}/generate-outfits` 批量生成接口
- 生成时将角色 appearance + outfit 描述拼接为 prompt 传给 ComfyUI
- 图片输出到 `assets/characters/{char_id}/{outfit_key}/` 子目录

### 2026-05-27 前端显示层
- ID→中文名映射（网格视图、时间线、分镜表格 tooltip）
- 编辑弹窗选择器：value 存 ID，显示中文名
- 解除角色/场景名强制中文限制（允许英文名）
- action_en 为空时自动翻译中文 action 给 ComfyUI
- outfit 字段接入参考图查找链路（优先 outfit 子目录）

### 2026-05-27 代码审查（三轮共 17 项）
- pipeline/tasks.py — `except Exception:` 缺少 `as e`（8 处）
- web/routers/api.py — `async def` → `def`（2 处）
- infra/database/pool.py — cursor 泄漏
- api/backends/image/comfyui.py — 连接池复用 + 指数退避 + subfolder URL 编码
- pipeline/producer.py — 接入 `build_upload_map` + `upload_image`
- engines/prompt.py — HTTP 翻译 API 兜底 + 翻译缓存上限
- engines/llm_generator.py — 单引号改用 `ast.literal_eval` 优先
- api/backends/seko/proposal.py — 30 分钟超时保护
- api/backends/tts/mimo_*.py — WAV 格式参数提取为类常量
- infra/retry.py — `max_retries=0` 边界处理
- infra/ffmpeg.py — SRT 路径转义补全
- engines/quality.py — 复用 `infra.ffmpeg.probe`
- engines/workflow.py — negative prompt 检测改进
- engines/workflow_builder.py — CLIP 节点反向追踪
- api/backends/llm/ollama.py — health_check 携带 API key
- api/registry.py — 配置查找兼容原始名和规范化名
- engines/emotions.py — 情绪匹配优先更长关键词
- post/vertical.py — 人脸检测多帧采样

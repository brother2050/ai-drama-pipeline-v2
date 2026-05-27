# TODO — 待开发功能

> 更新：2026-05-27

---

## 🔴 待优化（清理兼容包袱）

### 1. engines/gpu_adapter.py — 移除废弃 vram_mb 参数
- `vram_mb` 参数标注"已废弃，保留兼容性，忽略"
- 个人项目直接删掉这个参数，调用方也不需要传

### 2. infra/gpu.py — 移除废弃 detect_gpu() 函数
- 标注"兼容旧接口 — 返回占位信息（不检测本地 GPU）"
- 直接删除，调用方改用 `get_generation_config()`

### 3. web/schemas + web/routers/api.py — ConfigUpdate 简化
- `ConfigUpdate.get_config_data()` 兼容 `{"data":{}}` 和 `{"project":{}}` 两种格式
- 个人项目只保留 `{"data":{}}` 新格式即可
- 涉及文件：`web/schemas/__init__.py`（L134-148）、`web/routers/api.py`（L645-655）

### 4. api/backends/llm/ollama.py — 移除 /v1 后缀兼容
- `url.endswith("/v1")` 自动 strip，用户填错自己负责

### 5. infra/http.py — 移除 CloudStudio 双认证头
- 同时发 `X-API-Key` + `Authorization: Bearer`，只为兼容 CloudStudio 代理
- 个人项目用不到 CloudStudio，只保留 `Authorization: Bearer`

---

## ✅ 已完成

### 2026-05-27 outfits 统一为 dict 格式
- 移除 pipeline/tasks.py 中 string/dict 双格式兼容逻辑
- engines/llm_generator.py LLM prompt + _normalize_character 统一 dict
- web/static/js/app.js 前端三处始终用 dict
- projects/default 角色 YAML + 项目模板迁移

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

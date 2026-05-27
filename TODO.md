# TODO — 代码审查问题清单

> 审查日期：2026-05-27 | 更新：2026-05-27
> 个人使用场景，已排除安全/分布式/生产环境相关项

---

## ✅ 全部已修复

### 第一轮（高优先级）
- `pipeline/tasks.py` — `except Exception:` 缺少 `as e`（8 处）
- `web/routers/api.py` — `async def` → `def`（2 处）
- `infra/database/pool.py` — cursor 泄漏
- `api/backends/image/comfyui.py` — 连接池复用 + 指数退避 + subfolder URL 编码
- `pipeline/producer.py` — 接入 `build_upload_map` + `upload_image`
- `engines/prompt.py` — HTTP 翻译 API 兜底（LLM→HTTP→原文三级降级）

### 第二轮（中优先级 bug）
- `engines/llm_generator.py` — 单引号替换改用 `ast.literal_eval` 优先解析
- `engines/prompt.py` — 翻译缓存加 4096 上限
- `api/backends/seko/proposal.py` — `wait_for_proposal` 加 max_retries=180（30 分钟超时）
- `api/backends/tts/mimo_*.py` — WAV 格式参数提取为类常量
- `infra/retry.py` — `max_retries=0` 边界处理
- `infra/ffmpeg.py` — SRT 路径转义补全 `=` 和 `%`

### 第三轮（优化类）
- `engines/quality.py` — 复用 `infra.ffmpeg.probe` 替代硬编码 subprocess
- `engines/workflow.py` — negative prompt 检测改进（更精确的关键词 + 长度判断）
- `engines/workflow_builder.py` — CLIP 节点查找改用 KSampler 输入反向追踪
- `api/backends/llm/ollama.py` — health_check 携带 API key
- `api/registry.py` — 配置查找同时尝试原始名和规范化名

---

## ⚪ 剩余低优先级（不影响功能，可后续优化）

- `engines/video_consistency.py` — 临时目录清理（OS 自动回收，非 bug）
- `pipeline/tasks.py` — advisory lock crc32 碰撞（概率极低）
- `pipeline/tasks.py` — shot_task 同步调用（设计选择，非 bug）
- `post/vertical.py` — 仅第一帧人脸检测（功能限制，非 bug）
- `engines/emotions.py` — 子串匹配（功能限制，非 bug）

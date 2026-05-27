# TODO — 代码审查问题清单

> 审查日期：2026-05-27 | 更新：2026-05-27
> 个人使用场景，已排除安全/分布式/生产环境相关项

---

## 🔧 待修复（实际 bug 或会产生错误结果）

- [ ] **`engines/llm_generator.py`** — `_parse_json_response` 单引号替换会破坏值中的单引号（如 `it's` → 解析失败）
- [ ] **`engines/llm_generator.py`** — LLM 输出非 JSON 时静默返回空列表，无重试
- [ ] **`engines/prompt.py`** — `_translate_cache` 无大小限制，长时间运行可能内存膨胀
- [ ] **`api/backends/seko/proposal.py`** — `wait_for_proposal` 是 `while True`，API 持续返回 RUNNING 时永远阻塞，需加最大重试
- [ ] **`api/backends/tts/mimo_*.py`** — WAV header 硬编码 `sr=24000, bps=16, ch=1`，实际采样率不同时产生损坏文件
- [ ] **`infra/retry.py`** — `max_retries=0` 时 `raise last_exc` 会抛 `None`
- [ ] **`infra/ffmpeg.py`** — `add_subtitle` 对 SRT 路径的转义不完整（缺 `=` 和 `%`），特殊字符路径会导致 ffmpeg 失败

## ⚪ 可优化（不影响功能，改善代码质量）

- [ ] **`engines/video_consistency.py`** — 临时目录在正常返回后可能泄漏
- [ ] **`engines/video_consistency.py`** — `_extract_embedding` 用函数属性存全局 app，与 `consistency.py` 不一致
- [ ] **`engines/workflow_builder.py`** — `_inject_lora` 找 CLIP 节点逻辑可能匹配到不相关节点
- [ ] **`api/backends/llm/ollama.py`** — `health_check` 未携带 API key，可能被 401 拒绝
- [ ] **`pipeline/tasks.py`** — `_try_mark_running_atomic` 的 advisory lock 用 `zlib.crc32`，有碰撞风险（概率极低）
- [ ] **`pipeline/tasks.py`** — `shot_task` 用 `apply`（同步调用），无法利用 Celery 并发
- [ ] **`api/registry.py`** — `Container._backend_config` 中 `name.replace("-", "_")` 可能导致配置键不匹配
- [ ] **`infra/transitions.py`** — `build_concat_filter` 的 `offset` 计算对短视频可能偏差
- [ ] **`post/vertical.py`** — `_find_face_center` 仅读第一帧检测人脸，无人脸时回退模糊
- [ ] **`engines/emotions.py`** — 情绪关键词子串匹配可能误匹配
- [ ] **`engines/quality.py`** — `check_video_format` 中 ffprobe 硬编码，应复用 `infra.ffmpeg.probe`
- [ ] **`engines/workflow.py`** — `set_clip_text_prompts` 通过 "bad"/"worst" 判断 negative prompt，可能误判

## ✅ 已修复

- `pipeline/tasks.py` — `except Exception:` 缺少 `as e`（8 处）
- `web/routers/api.py` — `async def` → `def`（2 处）
- `infra/database/pool.py` — cursor 泄漏
- `api/backends/image/comfyui.py` — 连接池复用 + 指数退避 + subfolder URL 编码
- `pipeline/producer.py` — 接入 `build_upload_map` + `upload_image`
- `engines/prompt.py` — HTTP 翻译 API 兜底（LLM→HTTP→原文三级降级）

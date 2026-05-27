# TODO — 代码审查问题清单

> 审查日期：2026-05-27
> 共扫描 78 个 Python 文件，发现 6 高 + 25 中 + 30+ 低

---

## 🔴 高严重度（6 个）

- [x] **`pipeline/tasks.py`** — `except Exception:` 里引用变量 `e` 但没写 `as e`，导致 `NameError` 被吞掉。涉及 `ai_storyboard_task`、`ai_characters_task`、`ai_scenes_task`、`seko_import_task`
- [ ] **`engines/prompt.py`** — 外部翻译 API 用 HTTP 明文传输用户文本，有数据泄露风险；地址硬编码应走配置
- [x] **`infra/database/pool.py`** — `connect()` 健康检查执行 `SELECT 1` 后未关闭 cursor，长期运行连接泄漏
- [x] **`web/routers/api.py`** — `_check_rate_limit` 用内存存储，多 worker 进程下无法共享状态，限流形同虚设
- [x] **`web/routers/api.py`** — `generate_character_portrait` 和 `generate_scene_image` 是 `async def` 但内部执行大量同步 I/O，阻塞事件循环
- [ ] **`engines/portrait.py`** — `_generating` 集合是模块级全局状态，多进程（Celery 多 worker）下无法提供重入保护，需用分布式锁

## 🟡 中严重度（25 个）

- [ ] **`engines/llm_generator.py`** — `_parse_json_response` 的单引号替换会破坏 JSON 值中的单引号（如 `it's`）
- [ ] **`engines/llm_generator.py`** — LLM 输出非 JSON 时静默返回空列表，无重试机制
- [ ] **`engines/prompt.py`** — `_translate_cache` 无大小限制，长期运行可能 OOM
- [ ] **`engines/video_consistency.py`** — 临时目录在正常返回后可能泄漏（`_cleanup_frames` 清理文件但不一定清目录）
- [ ] **`engines/video_consistency.py`** — `_extract_embedding` 用函数属性存全局 app，与 `consistency.py` 实现不一致
- [ ] **`engines/workflow_builder.py`** — `_inject_lora` 找 CLIP 节点逻辑可能匹配到不相关节点
- [x] **`api/backends/image/comfyui.py`** — 轮询 `/history` 用 `time.sleep(2)` 忙等待，ComfyUI 宕机时阻塞最多 900 秒
- [x] **`api/backends/image/comfyui.py`** — `_download_outputs` 的 `subfolder` 参数直接拼 URL，有路径遍历风险
- [x] **`api/backends/image/comfyui.py`** — 每次 `generate` 创建新 `httpx.Client`，不复用连接池
- [ ] **`api/backends/tts/mimo_*.py`** — WAV header 硬编码 `sr=24000, bps=16, ch=1`，实际采样率不同时产生损坏文件
- [ ] **`api/backends/seko/proposal.py`** — `wait_for_proposal` 是 `while True` 无限循环，API 持续返回 RUNNING 时永远阻塞
- [ ] **`api/backends/seko/proposal.py`** — `download_image` 用 `urllib.request` 而非统一的 `httpx`，未校验 Content-Type
- [ ] **`api/registry.py`** — `Container._backend_config` 中 `name.replace("-", "_")` 可能导致配置键不匹配
- [ ] **`pipeline/celery_app.py`** — `format_task_error` 包含完整 traceback，持久化到 Redis 可能泄露敏感信息
- [ ] **`pipeline/tasks.py`** — `_try_mark_running_atomic` 的 advisory lock 用 `zlib.crc32`，有碰撞风险
- [ ] **`pipeline/tasks.py`** — `shot_task` 用 `apply`（同步调用），无法利用 Celery 并发
- [ ] **`pipeline/producer.py`** — 首帧失败后仍尝试执行视频和口型同步，产生无意义错误
- [ ] **`web/app.py`** — 全局异常处理返回 `{type(exc).__name__}: {str(exc)}`，生产环境泄露内部细节
- [ ] **`web/routers/api.py`** — `save_storyboard` 的 `.lock` 文件不会自动清理
- [ ] **`web/routers/api.py`** — `seko_proposal_status` 的 `download_dir` 可能绕过 `_safe_path` 检查
- [ ] **`infra/http.py`** — `auth_headers` 同时发 `X-API-Key` 和 `Authorization`，多余 header 泄露 key
- [ ] **`infra/retry.py`** — `max_retries=0` 时 `raise last_exc` 会抛 `None`
- [ ] **`infra/ffmpeg.py`** — `add_subtitle` 对 SRT 路径的转义不完整（缺 `=` 和 `%`）
- [ ] **`infra/transitions.py`** — `build_concat_filter` 的 `offset` 计算对短视频可能偏差
- [ ] **`post/vertical.py`** — `_find_face_center` 仅读第一帧检测人脸，无人脸时回退模糊

## 🟢 低严重度（30+ 个）

- [ ] **多文件** — `_row_to_dict` 在 `characters.py`、`episodes.py`、`scenes.py`、`shots.py`、`generation.py` 重复定义，应抽取公共模块
- [ ] **`api/backends/tts/cosyvoice.py`、`fish_speech.py`、`gpt_sovits.py`** — 代码风格过于紧凑（单行多语句），可读性差
- [ ] **`api/backends/llm/ollama.py`** — `health_check` 访问 `/v1/models` 未携带 API key，可能被 401 拒绝
- [ ] **`web/app.py`** — CORS 默认 `allow_origins=["*"]`，生产环境应限制
- [ ] **`web/services/__init__.py`** — `setup_logging` 使用 `force=True` 会覆盖第三方库日志配置
- [ ] **`infra/redis_mgr.py`** — macOS Homebrew 路径硬编码
- [ ] **`infra/text.py`** — `sanitize_filename` 未处理空格和 Windows 保留名
- [ ] **`infra/gpu.py`** — `get_generation_config` 无法加载 Config 时静默返回默认值
- [ ] **`engines/consistency.py`** — `_extract_hash` 返回 32 维伪向量，余弦相似度精度极低
- [ ] **`engines/emotions.py`** — 情绪关键词子串匹配可能误匹配（如"苦笑"→ happy）
- [ ] **`engines/quality.py`** — `check_video_format` 中 ffprobe 命令硬编码，应复用 `infra.ffmpeg.probe`
- [ ] **`engines/workflow.py`** — `set_clip_text_prompts` 通过 "bad"/"worst" 判断 negative prompt，可能误判
- [ ] **`flow/model_registry.py`** — 实现合理，无明显问题
- [ ] **`engines/storyboard.py`** — 原子写入实现良好
- [ ] **`post/subtitle.py`** — 实现简洁正确

---

## 🔧 ComfyUI 集成问题

- [x] **角色定妆照 → ComfyUI** — 只写了文件名到工作流节点，没有调用 `comfyui.upload_image()`，跨机器部署时 IP-Adapter 参考图会找不到
- [x] **场景参考图 → ComfyUI** — 同上，只写文件名没 upload
- [x] **`build_upload_map` 死代码** — `workflow_builder.py` 中定义了 `build_upload_map()` 方法（构建参考图上传映射），但全项目无人调用，是死代码 → 已在 `tasks.py:first_frame_core` 和 `producer.py:_produce_shot` 中接入
- [x] **首帧 → ComfyUI** — ✅ 有串联，`build_first_frame` 构建工作流 → `comfyui.generate` 提交
- [x] **首帧 → 视频** — ✅ 有串联，`frame.png` 路径传入 `build_video`

---

## 建议修复优先级

1. ~~`pipeline/tasks.py` — `except Exception:` 变量引用 bug~~ ✅
2. ~~`web/routers/api.py` — `async def` → `def`；rate limiting 改 Redis~~ ✅ (async→def 已修，Redis rate limiting 个人使用暂不需要)
3. ~~`infra/database/pool.py` — cursor 泄漏~~ ✅
4. `engines/prompt.py` — 翻译 API 改 HTTPS + 走配置
5. `engines/portrait.py` — 分布式锁替代全局集合 (个人单 worker 可暂不修)
6. ~~`api/backends/image/comfyui.py` — 连接池复用 + 超时优化~~ ✅
7. ~~ComfyUI 集成 — 补充 upload_image 调用，清理死代码~~ ✅

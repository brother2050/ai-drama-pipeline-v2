# 重构方案：消除硬编码，注册表驱动一切

> 核心原则：`models_registry.yaml` 是所有后端元数据的唯一真相来源。
> 代码中不再出现任何后端名的 if/elif，新增后端只改 YAML，不改代码。

---

## 一、设计总览

### 重构前（现状）

```
代码中散落 16+ 处后端名硬编码
  ↓
新增后端 = 改 8 个文件 + 注册表
  ↓
容易遗漏 → 运行时 bug
```

### 重构后（目标）

```
models_registry.yaml 声明一切元数据
  ↓
代码通过 ModelRegistry 查询
  ↓
新增后端 = 只改 YAML + 写后端模块
```

### 变更范围

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `config/models_registry.yaml` | **重写** | 扩展为全量后端元数据 |
| `flow/model_registry.py` | **重写** | 统一查询接口，覆盖所有服务类型 |
| `infra/toolcheck.py` | **重写** | 注册表驱动，消除 if-elif 链 |
| `engines/prompt.py` | **重构** | prompt 风格从注册表查询 |
| `engines/workflow_builder.py` | **重构** | 一致性方案、帧数参数从注册表查询 |
| `web/routers/api.py` | **重构** | test_tool 委托给 ModelRegistry |
| `pipeline/tasks.py` | **小改** | 步骤编排从注册表读取（可选） |
| `cli.py` | **小改** | 默认后端名从注册表读取 |
| `infra/config.py` | **小改** | DEFAULTS 中的后端名从注册表读取 |

---

## 二、注册表扩展设计

### 2.1 新版 `models_registry.yaml` 结构

```yaml
# ============================================================
# 模型注册表 — 所有后端元数据的唯一真相来源
# ============================================================

# ── 全局默认后端 ──
defaults:
  tts_backend: "mimo-voicedesign"
  lip_sync_backend: "musetalk"
  music_backend: "template"
  image_backend: "sd15"
  video_backend: "animatediff"
  llm_backend: "openai"

# ── TTS 后端 ──
tts_backends:
  mimo-voicedesign:
    description: "MiMo VoiceDesign（云API，免费）"
    requires_api_key: true
    api_key_env: "MIMO_API_KEY"
    health_check:
      type: "api_key_env"        # 检测类型：api_key_env / http / command
      env: "MIMO_API_KEY"
    test:
      type: "mimo_connect"       # 实际连接测试类型

  mimo-voiceclone:
    description: "MiMo VoiceClone（云API，参考音频克隆声音）"
    requires_api_key: true
    api_key_env: "MIMO_API_KEY"
    health_check:
      type: "api_key_env"
      env: "MIMO_API_KEY"

  gpt-sovits:
    description: "GPT-SoVITS（本地部署，开源）"
    health_check:
      type: "http"
      path: "/"
      config_key: "models.gpt_sovits.api_url"

  cosyvoice:
    description: "CosyVoice（本地部署，多语言）"
    health_check:
      type: "http"
      path: "/"
      config_key: "models.cosyvoice.api_url"

  fish-speech:
    description: "Fish-Speech（本地部署，轻量）"
    health_check:
      type: "http"
      path: "/"
      config_key: "models.fish_speech.api_url"

# ── 口型同步后端 ──
lipsync_backends:
  musetalk:
    description: "MuseTalk（本地部署，效果好）"
    health_check:
      type: "http"
      path: "/"
      config_key: "models.musetalk.api_url"

  wav2lip:
    description: "Wav2Lip（本地部署，轻量）"
    health_check:
      type: "http"
      path: "/"
      config_key: "models.wav2lip.api_url"

# ── LLM 后端 ──
llm_backends:
  openai:
    description: "OpenAI 兼容 API"
    requires_api_key: true
    health_check:
      type: "openai_models"      # OpenAI 兼容 /v1/models
      config_key: "llm.base_url"
      api_key_from: "llm.api_key"

  ollama:
    description: "Ollama（本地部署）"
    health_check:
      type: "ollama_tags"        # Ollama /api/tags
      config_key: "llm.base_url"

# ── 配乐后端 ──
music_backends:
  template:
    description: "ffmpeg 模板配乐（开箱即用）"
    health_check:
      type: "command"
      command: "ffmpeg"

# ── 图像后端 ──
image_backends:
  sd15:
    workflow: "01_first_frame_sd15.json"
    prompt_style: "tag"           # tag = 逗号分隔（CLIP 编码器）
    consistency_default: "ip_adapter"
    default_params:
      width: 512
      height: 512
      steps: 20
      cfg_scale: 7.5

  flux:
    workflow: "01_first_frame_flux.json"
    prompt_style: "natural"       # 自然语言段落（T5 编码器）
    consistency_default: "pulid_flux"
    default_params:
      width: 1024
      height: 576
      steps: 28
      cfg_scale: 3.5

  cosmos:
    workflow: "cosmos_predict2_2B_t2i.json"
    prompt_style: "natural"
    consistency_default: "none"   # Cosmos 仅支持 LoRA 训练
    default_params:
      width: 1024
      height: 576
      steps: 35
      cfg_scale: 4

# ── 视频后端 ──
video_backends:
  animatediff:
    workflow: "02_img2video.json"
    sampler_node: "KSampler"
    frame_params:                 # 帧数注入规则（替代硬编码的 _set_video_frames）
      node_class: "ADE_StandardStaticContextOptions"
      input_name: "context_length"
    default_params:
      frames: 8
      fps: 8
      steps: 15
      denoise: 0.5

  cogvideox:
    workflow: "03_img2video_cogvideo.json"
    sampler_node: "CogVideoXSampler"
    frame_params:
      node_class: "EmptyLatentImage"
      input_name: "batch_size"
    default_params:
      width: 720
      height: 480
      frames: 16
      fps: 12
      steps: 20
      denoise: 0.55

  cosmos-video:
    workflow: "04_img2video_cosmos.json"
    sampler_node: "KSampler"
    frame_params:
      node_class: "CosmosPredict2ImageToVideoLatent"
      input_name: "length"
    default_params:
      width: 848
      height: 480
      frames: 93
      fps: 16
      steps: 35
      denoise: 1

# ── 一致性方案 ──
consistency_methods:
  ip_adapter:
    description: "IP-Adapter Plus（SD1.5/SDXL 面部一致性）"
    compatible_backends: ["sd15", "sdxl"]
    config_key: "ip_adapter"
    inject_function: "inject_ip_adapter"    # WorkflowBuilder 中的注入方法名

  pulid_flux:
    description: "PuLID-Flux（Flux 面部一致性）"
    compatible_backends: ["flux"]
    config_key: "pulid_flux"
    inject_function: "inject_pulid_flux"

  none:
    description: "无面部一致性（仅靠 LoRA + seed）"
    compatible_backends: ["*"]              # 兼容所有后端

# ── 辅助服务（非后端，但需要健康检查） ──
services:
  comfyui:
    description: "ComfyUI 图像/视频生成服务"
    health_check:
      type: "http"
      path: "/system_stats"
      config_key: "comfyui.url"
      api_key_from: "comfyui.api_key"

  redis:
    description: "Redis 任务队列"
    health_check:
      type: "port"
      host: "127.0.0.1"
      port: 6379

  celery:
    description: "Celery Worker"
    health_check:
      type: "celery_active"

  ffmpeg:
    description: "FFmpeg 视频处理"
    health_check:
      type: "command"
      command: "ffmpeg"

  seko:
    description: "Seko 影视策划案"
    health_check:
      type: "api_key_env"
      env: "SEKO_API_KEY"

  training:
    description: "AI Toolkit LoRA 训练"
    health_check:
      type: "http"
      path: "/api/gpu"
      config_key: "training.api_url"

# ── 生产步骤编排 ──
pipeline_steps:
  - name: "tts"
    task: "pipeline.step.tts"
    tool: "tts"
    timeout: 120
  - name: "first_frame"
    task: "pipeline.step.first_frame"
    tool: "comfyui"
    timeout: 300
  - name: "video"
    task: "pipeline.step.video"
    tool: "comfyui"
    timeout: 600
  - name: "lipsync"
    task: "pipeline.step.lipsync"
    tool: "lipsync"
    timeout: 300
```

### 2.2 设计要点

1. **`defaults` 段**：全局默认后端名，替代 `infra/config.py` 中的硬编码 DEFAULTS
2. **每个后端声明 `health_check`**：类型 + 参数，`toolcheck.py` 通用执行，不再 if-elif
3. **图像后端声明 `prompt_style`**：`tag` 或 `natural`，`prompt.py` 查询注册表
4. **图像后端声明 `consistency_default`**：替代 `workflow_builder.py` 中的硬编码映射
5. **视频后端声明 `frame_params`**：节点类名 + 参数名，替代 `_set_video_frames()` 的硬编码
6. **`consistency_methods` 段**：声明一致性方案与后端的兼容关系
7. **`pipeline_steps` 段**：声明步骤编排（可选，Phase 2 实现）

---

## 三、ModelRegistry 扩展

### 3.1 新增方法

```python
class ModelRegistry:
    # ── 已有（保留） ──
    def get_image_workflow(self, backend: str) -> str
    def get_video_workflow(self, backend: str) -> str
    def get_image_defaults(self, backend: str) -> dict
    def get_video_defaults(self, backend: str) -> dict

    # ── 新增：统一查询接口 ──
    def get_defaults(self) -> dict[str, str]:
        """返回全局默认后端名映射 {'tts_backend': 'mimo-voicedesign', ...}"""

    def get_backend(self, service_type: str, name: str) -> dict | None:
        """通用后端查询。service_type: tts/lipsync/llm/music/image/video"""

    def get_backends(self, service_type: str) -> dict[str, dict]:
        """返回某服务类型的所有后端 {'name': {metadata}}"""

    def get_health_check(self, service_type: str, name: str) -> dict | None:
        """返回后端的健康检查配置"""

    def get_prompt_style(self, image_backend: str) -> str:
        """返回图像后端的 prompt 风格 ('tag' / 'natural')"""

    def get_consistency_default(self, image_backend: str) -> str:
        """返回图像后端的默认一致性方案"""

    def get_frame_params(self, video_backend: str) -> dict | None:
        """返回视频后端的帧数注入规则 {node_class, input_name}"""

    def get_consistency_method(self, name: str) -> dict | None:
        """返回一致性方案的元数据"""

    def get_compatible_consistency(self, image_backend: str) -> list[str]:
        """返回与某图像后端兼容的所有一致性方案"""

    def get_pipeline_steps(self) -> list[dict]:
        """返回生产步骤编排列表"""

    def get_all_health_checks(self) -> dict[str, dict]:
        """返回所有需要健康检查的项（后端 + 辅助服务）"""
```

---

## 四、各模块重构方案

### 4.1 `infra/toolcheck.py` — 注册表驱动

**重构前**（200 行 if-elif）：
```python
def _check_tool_inner(name, cfg):
    if name == "tts":
        backend = cfg.get("models", {}).get("tts_backend", "mimo-voicedesign")
        if "mimo" in backend:
            ...  # 30 行
    elif name == "comfyui":
        ...  # 10 行
    elif name == "lipsync":
        ...  # 10 行
    # ... 150 行
```

**重构后**（~60 行通用引擎）：
```python
def check_tool(name: str, cfg: dict) -> dict:
    """检测工具可用性（注册表驱动）"""
    registry = _get_registry()

    # 1. 查注册表（后端 or 辅助服务）
    hc = registry.get_health_check_for(name, cfg)
    if not hc:
        return {"available": False, "backend": name, "reason": "未注册"}

    # 2. 通用执行健康检查
    return _execute_health_check(name, hc, cfg)


def _execute_health_check(name: str, hc: dict, cfg: dict) -> dict:
    """通用健康检查执行器"""
    check_type = hc.get("type", "")

    if check_type == "api_key_env":
        env = hc.get("env", "")
        ok = bool(os.environ.get(env) or _get_cfg_key(cfg, hc.get("config_key", "")))
        return _result(name, ok, f"{env} 未配置" if not ok else "")

    elif check_type == "http":
        url = _resolve_url(cfg, hc.get("config_key", ""))
        headers = _resolve_auth(cfg, hc.get("api_key_from", ""))
        ok = _url_ok(url, hc.get("path", "/"), headers)
        return _result(name, ok, f"服务不可达 ({url})" if not ok else "")

    elif check_type == "ollama_tags":
        url = _resolve_url(cfg, hc.get("config_key", ""))
        ok = _url_ok(url, "/api/tags")
        return _result(name, ok, f"Ollama 不可达 ({url})" if not ok else "")

    elif check_type == "openai_models":
        url = _resolve_url(cfg, hc.get("config_key", ""))
        headers = _resolve_auth(cfg, hc.get("api_key_from", ""))
        check_url = url.rstrip("/") + ("/v1" if not url.rstrip("/").endswith("/v1") else "")
        ok = _url_ok(check_url, "/models", headers)
        return _result(name, ok, f"LLM 不可达 ({url})" if not ok else "")

    elif check_type == "command":
        cmd = hc.get("command", "")
        ok = bool(shutil.which(cmd))
        return _result(name, ok, f"{cmd} 未安装" if not ok else "")

    elif check_type == "port":
        ok = _port_ok(hc.get("port", 0))
        return _result(name, ok, f"端口 {hc.get('port')} 未监听" if not ok else "")

    elif check_type == "celery_active":
        # ... 现有逻辑

    return _result(name, False, "未知检查类型")
```

**效果**：新增工具只需在 YAML 中声明 `health_check`，不改代码。

### 4.2 `engines/prompt.py` — 注册表查询 prompt 风格

**重构前**：
```python
# engines/prompt.py:389
use_natural = backend_lower in ("flux", "cosmos")
```

**重构后**：
```python
def build_prompt(shot, character_desc="", scene_desc="", style="cinematic",
                 genre="urban", image_backend="", registry=None):
    if registry is None:
        from flow.model_registry import ModelRegistry
        registry = ModelRegistry(...)  # 从配置路径创建

    prompt_style = registry.get_prompt_style(image_backend) or "tag"

    if prompt_style == "natural":
        return _build_natural_prompt(...)
    else:
        return _build_tag_prompt(...)
```

**效果**：新增第三种 prompt 风格（如 `structured`），只需在 YAML 中为后端声明 `prompt_style: "structured"`，然后在 `prompt.py` 加一个 `_build_structured_prompt()` 函数。

### 4.3 `engines/workflow_builder.py` — 三处硬编码消除

#### 4.3.1 一致性方案选择

**重构前**：
```python
if consistency == "auto":
    is_flux = img_backend.lower() == "flux"
    is_sd = img_backend.lower() in ("sd15", "sdxl")
    if is_flux: consistency = "pulid_flux"
    elif is_sd: consistency = "ip_adapter"
    else: consistency = "none"
```

**重构后**：
```python
if consistency == "auto":
    consistency = registry.get_consistency_default(img_backend) or "none"
```

#### 4.3.2 一致性方案注入分发

**重构前**：
```python
if consistency == "pulid_flux":
    wf = self._inject_pulid_flux(...)
elif consistency == "ip_adapter":
    wf = self._inject_ip_adapter_plus(...)
```

**重构后**：
```python
method_meta = registry.get_consistency_method(consistency)
if method_meta and method_meta.get("inject_function"):
    inject_fn = getattr(self, method_meta["inject_function"])
    wf = inject_fn(wf, chars_with_refs, config, outfit=outfit)
```

#### 4.3.3 视频帧数参数注入

**重构前**：
```python
def _set_video_frames(self, wf, frames, backend):
    for nid, node in wf.items():
        ct = node.get("class_type", "")
        if ct == "ADE_StandardStaticContextOptions" and "context_length" in inp:
            inp["context_length"] = frames      # AnimateDiff
        if ct == "EmptyLatentImage" and backend == "cogvideox":
            inp["batch_size"] = frames           # CogVideoX
        if ct == "CosmosPredict2ImageToVideoLatent" and "length" in inp:
            inp["length"] = frames               # Cosmos
```

**重构后**：
```python
def _set_video_frames(self, wf, frames, backend):
    frame_cfg = self.registry.get_frame_params(backend)
    if not frame_cfg:
        logger.warning(f"视频后端 '{backend}' 未声明 frame_params")
        return
    target_class = frame_cfg["node_class"]
    target_input = frame_cfg["input_name"]
    for nid, node in wf.items():
        if node.get("class_type") == target_class:
            node["inputs"][target_input] = frames
```

### 4.4 `web/routers/api.py` — test_tool 统一

**重构前**：`test_tool()` 是 100+ 行 if-elif，与 `toolcheck.py` 逻辑重叠。

**重构后**：
```python
@router.post("/tools/{name}/test")
def test_tool(name: str):
    cfg = _merged_cfg()
    # 基础可用性检查（委托给 toolcheck）
    result = _check_tool(name, cfg)
    if not result.get("available"):
        return {"ok": False, "name": name, "message": result.get("reason", ""), **result}

    # 实际连接测试（从注册表获取测试方法）
    registry = _get_registry()
    test_cfg = registry.get_test_config(name)
    if not test_cfg:
        return {"ok": True, "name": name, "message": "可用", **result}

    return _execute_test(name, test_cfg, cfg, result)
```

**效果**：`_execute_test()` 是通用测试执行器，各后端的测试逻辑在 YAML 中声明。

### 4.5 `infra/config.py` — 默认值从注册表读取

**重构前**：
```python
DEFAULTS = {
    "models": {"tts_backend": "mimo-voicedesign", "lip_sync_backend": "musetalk",
               "music_backend": "template", "image_backend": "sd15", "video_backend": "animatediff"},
    ...
}
```

**重构后**：
```python
def _load_registry_defaults() -> dict:
    """从 models_registry.yaml 读取全局默认后端名"""
    from flow.model_registry import ModelRegistry
    try:
        reg = ModelRegistry(...)
        defaults = reg.get_defaults()
        return {"models": defaults}
    except Exception:
        # 回退到硬编码（注册表不存在时）
        return {"models": {"tts_backend": "mimo-voicedesign", ...}}
```

### 4.6 `cli.py` — 默认后端名从注册表读取

**重构前**：
```python
tts = cfg.get("models", {}).get("tts_backend", "mimo-voicedesign")
```

**重构后**：
```python
from flow.model_registry import ModelRegistry
reg = ModelRegistry(cfg_path)
default_tts = reg.get_defaults().get("tts_backend", "mimo-voicedesign")
tts = cfg.get("models", {}).get("tts_backend", default_tts)
```

---

## 五、实施计划

### Phase 1：注册表扩展 + ModelRegistry（基础层）

**目标**：注册表包含所有元数据，ModelRegistry 提供统一查询接口。

| 步骤 | 文件 | 说明 |
|------|------|------|
| 1.1 | `config/models_registry.yaml` | 扩展结构（新增 defaults / health_check / prompt_style / consistency / frame_params / pipeline_steps） |
| 1.2 | `flow/model_registry.py` | 新增所有查询方法 |
| 1.3 | `tests/test_registry.py` | 注册表查询测试 |

**验收标准**：`ModelRegistry` 能返回任何后端的任何元数据，零硬编码。

### Phase 2：toolcheck 注册表驱动

**目标**：`toolcheck.py` 从 200 行 if-elif 变为 60 行通用引擎。

| 步骤 | 文件 | 说明 |
|------|------|------|
| 2.1 | `infra/toolcheck.py` | 重写为注册表驱动 |
| 2.2 | `web/routers/api.py` | test_tool 委托给 toolcheck + 注册表 |
| 2.3 | `tests/test_toolcheck.py` | 验证所有工具检测 |

**验收标准**：新增工具只需改 YAML，不改代码。

### Phase 3：workflow_builder 解耦

**目标**：消除一致性方案、帧数参数的硬编码。

| 步骤 | 文件 | 说明 |
|------|------|------|
| 3.1 | `engines/workflow_builder.py` | 一致性方案从注册表查询 |
| 3.2 | `engines/workflow_builder.py` | 帧数参数从注册表查询 |
| 3.3 | `engines/workflow_builder.py` | 一致性注入方法分发改为注册表驱动 |
| 3.4 | `tests/test_workflow_builder.py` | 验证各后端组合 |

**验收标准**：新增图像/视频后端不改 workflow_builder.py。

### Phase 4：prompt 风格解耦

**目标**：prompt 构建风格从注册表查询。

| 步骤 | 文件 | 说明 |
|------|------|------|
| 4.1 | `engines/prompt.py` | build_prompt 查询注册表获取 prompt_style |
| 4.2 | `engines/prompt.py` | 传入 registry 实例（避免循环依赖） |
| 4.3 | `tests/test_prompt.py` | 验证 tag/natural 两种风格 |

**验收标准**：新增 prompt 风格只需改 YAML + 加一个构建函数。

### Phase 5：默认值 & 配置层清理

**目标**：Config 的默认值从注册表读取。

| 步骤 | 文件 | 说明 |
|------|------|------|
| 5.1 | `infra/config.py` | DEFAULTS 从注册表加载 |
| 5.2 | `cli.py` | 默认后端名从注册表读取 |
| 5.3 | `pipeline/tasks.py` | 步骤编排可选从注册表读取 |

**验收标准**：全局零后端名硬编码。

### Phase 6：清理 & 文档

| 步骤 | 文件 | 说明 |
|------|------|------|
| 6.1 | 全局 | grep 确认零后端名硬编码残留 |
| 6.2 | `docs/` | 更新架构文档 |
| 6.3 | `config/models_registry.yaml` | 添加注释说明每个字段的用途 |

---

## 六、风险控制

### 向后兼容

- 所有重构保持现有 API 接口不变（Web 路由、CLI 命令）
- 注册表缺失字段时回退到硬编码默认值（渐进式迁移）
- 旧版 `models_registry.yaml` 仍然可用（新字段可选）

### 测试策略

- 每个 Phase 完成后运行 `pytest tests/ -v` 确认无回归
- 新增注册表查询测试（覆盖所有后端组合）
- 新增 toolcheck 测试（覆盖所有健康检查类型）

### 回滚方案

- 每个 Phase 独立 commit，可单独回滚
- 注册表扩展是增量的（新增字段），不删除旧字段

---

## 七、预期收益

| 指标 | 重构前 | 重构后 |
|------|--------|--------|
| 新增后端需改文件数 | 8 | 1（仅后端模块）+ 1（YAML） |
| 新增工具需改文件数 | 2（toolcheck + api.py） | 0（仅 YAML） |
| 新增一致性方案需改文件数 | 1（workflow_builder） | 0（仅 YAML） |
| 新增 prompt 风格需改文件数 | 1（prompt.py） | 1（加函数）+ 1（YAML） |
| 后端名硬编码处数 | 16+ | 1（registry defaults） |
| toolcheck 代码行数 | 200 | ~60 |

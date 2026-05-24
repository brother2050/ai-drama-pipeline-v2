# 🔍 代码逻辑审查报告

> 审查时间: 2026-05-24
> 审查范围: 全项目源码（逐文件）

---

## ✅ 已修复项（前四轮 35 项，略）

---

## 🔴 本轮发现 — 逻辑缺失 / Bug（需修复）

### 1. Workflow JSON 模板文件缺失（Critical）

`workflows/` 目录只有 `README.md`，缺少实际工作流 JSON 文件：
- `01_first_frame_sd15.json`
- `01_first_frame_flux.json`
- `02_img2video.json`
- `03_img2video_cogvideo.json`

**影响**: `WorkflowBuilder._load_wf()` 找不到文件返回 `{}`，导致 `build_first_frame` / `build_video` 返回空 dict，整个 ComfyUI 管线（首帧 + 视频）完全不可用。

**修复**: 提供示例工作流 JSON 模板，或在 `_load_wf` 为空时抛出明确异常。

---

### 2. `translate_to_english` 无 LLM 支持 — 中文 prompt 无法翻译

**文件**: `pipeline/tasks.py` `_run_first_frame()`, `pipeline/preview.py`

`translate_to_english(char.get("appearance", ""))` 被调用时没有传 `llm` 参数，回退逻辑是直接返回中文原文。ComfyUI 的 CLIP 模型对中文 prompt 效果很差。

**修复**: 在 `_run_first_frame` 中获取 LLM 后端并传入：
```python
llm = cont.get("llm") if cfg.get("llm", {}).get("enabled") else None
char_descs.append(translate_to_english(c.get("appearance", ""), llm=llm))
```

---

### 3. `Container._backend_config` 中 `_project_dir` 永远为空

**文件**: `api/registry.py` `Container._backend_config()`

```python
"project_dir": self._config.get("_project_dir", ""),
```

但 `Config._data` 中从未设置 `_project_dir` 键。后端如 `MimoVoiceDesign` 和 `WorkflowBuilder` 依赖 `project_dir` 来定位资源文件。

**修复**: 在 `Config.__init__` 中注入：
```python
self._data["_project_dir"] = self._project_dir
```

---

### 4. ComfyUI 缺少 `upload_image` 方法 — 参考图无法上传

**文件**: `api/backends/image/comfyui.py`, `pipeline/tasks.py` `_run_first_frame()`

`_run_first_frame` 中调用：
```python
comfyui.upload_image(file_path, node_id) if hasattr(comfyui, 'upload_image') else None
```

但 `ComfyUI` 类没有实现 `upload_image` 方法。IP-Adapter 的参考图永远无法上传到 ComfyUI 服务器。

**修复**: 在 `ComfyUI` 类中添加 `upload_image` 方法：
```python
def upload_image(self, filepath: str, overwrite: bool = True) -> dict:
    with open(filepath, "rb") as f:
        r = httpx.post(f"{self._url}/upload/image",
                       files={"image": (Path(filepath).name, f)},
                       data={"overwrite": str(overwrite).lower()},
                       headers=self._headers())
        r.raise_for_status()
        return r.json()
```

---

### 5. `storyboard/episodes.csv` 缺少 `action_en` / `dialogue_en` 列

**文件**: `storyboard/episodes.csv`

CSV 只有 11 列：`episode,shot_id,scene,characters,action,dialogue,camera,shot_type,duration,outfit,emotion`

但 `WorkflowBuilder.build_first_frame()` 读取 `shot.get("action_en")` 和 `shot.get("dialogue_en")`，永远为空。

**修复**: CSV 增加两列，或在 `_run_first_frame` 中调用 `translate_to_english` 动态翻译。

---

### 6. `infra/database/schema.py` shots 表缺少 `action_en` / `dialogue_en` 列

**文件**: `infra/database/schema.py`

`shots` 表定义没有 `action_en` 和 `dialogue_en` 字段，与 CSV 数据结构不一致。

**修复**: schema 增加两列。

---

### 7. `post/production.py` 中间文件清理可能误删最终文件

**文件**: `post/production.py`

```python
shutil.copy2(str(concat_out), str(final_out))
# 后续清理:
for intermediate in [..., out_dir / f"episode_{episode:02d}_vertical.mp4"]:
    if intermediate.exists() and intermediate != final_out:
        intermediate.unlink()
```

当 `vertical=True` 时，`concat_out` 最终指向 `*_vertical.mp4`，而清理列表也包含 `*_vertical.mp4`。虽然 `intermediate != final_out` 保护了 `_final.mp4`，但 `_vertical.mp4`（当前的 `concat_out`）会被删除，而它已经被 `copy2` 到 `_final.mp4`，所以逻辑上没问题但浪费磁盘空间。

**更严重的问题**: 如果 `vertical=True` 且横转竖成功，`concat_out` 变成 `*_vertical.mp4`。但清理列表中的 `*_vertical.mp4` 会被删除（因为它不等于 `final_out`），这是正确行为。逻辑 OK，但代码可读性差。

**建议**: 重构为显式跟踪当前活跃文件。

---

### 8. `SadTalker` 后端注册但配置中无对应条目

**文件**: `api/backends/lipsync/musetalk.py`

`SadTalker` 在 `musetalk.py` 中注册（priority=50），但 `config/project.yaml` 的 `models` 中没有 `sadtalker` 配置。如果用户设置 `lip_sync_backend: sadtalker`，`Container._backend_config` 会用空 dict 创建实例，`api_url` 默认 `http://127.0.0.1:8082`。

**修复**: 在 `config/project.yaml.example` 中添加 `sadtalker` 配置示例。

---

### 9. `post/music.py` MusicGenerator 与 `api/backends/music/template.py` TemplateMusic 功能重复

两个模块都用 ffmpeg 生成简单音调配乐。`MusicGenerator._template()` 和 `TemplateMusic.generate()` 逻辑几乎相同。

**修复**: `MusicGenerator` 应该通过 `Container` 获取音乐后端，而非自己实现 `_template` / `_musicgen`。

---

### 10. `engines/workflow_builder.py` prompt 构建逻辑与 `engines/prompt.py` `build_prompt` 重复

**文件**: `engines/workflow_builder.py` `build_first_frame()`

`build_first_frame` 内联构建 prompt（拼接 style/genre/scene/character/action/emotion/shot_type/camera），而 `engines/prompt.py` 的 `build_prompt` 做同样的事情。代码重复，维护时容易不一致。

**修复**: `build_first_frame` 应调用 `build_prompt` 函数。

---

### 11. `cli.py` `run_all` 中 `produce` 命令错误传入 `vertical` 参数

**文件**: `cli.py` `run_all()`

```python
elif task_name == "pipeline.produce":
    _run_via_celery(task_name, cfg, episode, vertical=vertical)
```

`produce_task` 签名是 `(config_path, episode, vertical=False)`，但 `produce` 的语义是"完整生产"，`vertical` 应该只在 `post` 阶段生效。传给 `produce_task` 会导致它在内部调用 `_run_post` 时也传入 `vertical`，可能产生意外的横转竖。

**修复**: `produce` 不传 `vertical`，只在 `post` 阶段传：
```python
elif task_name == "pipeline.produce":
    _run_via_celery(task_name, cfg, episode)
```

---

### 12. `web/routers/api.py` `save_storyboard` 未同步数据库

**文件**: `web/routers/api.py` `save_storyboard()`

只写 CSV，不更新 PostgreSQL 的 `shots` 表。`flow/episode.py` 的 `get_episode_status` 会从数据库查询 `generation_status`，但 `shots` 表永远是空的（除非手动调用 `shots.upsert`）。

**修复**: `save_storyboard` 时同步更新数据库。

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
| `infra/http.py` ApiClient 未被使用 | 后端各自用 httpx.Client | 低 |
| `pipeline/preview.py` 与 tasks.py 重复 | CLI 用 tasks.py 版本 | 无 |
| `engines/consistency.py` 与 `video_consistency.py` 重复 | 各有侧重 | 低 |

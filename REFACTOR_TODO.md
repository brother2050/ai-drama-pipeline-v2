# 🔧 代码简洁重构 TODO

> 原则：提取工具函数，消除 if-null / 重复初始化 / 长 if-else 链

---

## ✅ 已完成

| # | 文件 | 改动 | 状态 |
|---|------|------|------|
| 1 | app.js | `_html()` / `_btnLoad()` 消除 if(el) el.innerHTML 冗余 | ✅ |
| 2 | app.js | `_runTool()` 合并 runPortraits/runPost/runSubtitle | ✅ |
| 3 | app.js | `_runAIGen()` 合并 doAIGenCharacter/doAIGenScene | ✅ |
| 4 | app.js | `_uploadImg()` / `_handleImgDrop()` 合并 ec/es 上传 | ✅ |
| 5 | api.py | `_check_id/_check_uuid/_check_filename/_check_episode/_check_entity_type` | ✅ |
| 6 | api.py | `_active_project_dir()` → `_proj()` 别名统一 | ✅ |
| 7 | tasks.py | `_init_ctx()` / `_cfg_dir()` 提取 | ✅ |
| 8 | tasks.py | `ai_storyboard_task` 用 `_init_ctx` 替代 6 行样板 | ✅ |
| 9 | tasks.py | `_shot_dir` 用 `_cfg_dir` 替换 (T5) | ✅ |
| 10 | tasks.py | `_run_subtitle` 用 `_init_ctx` + `_cfg_dir` 替换 (T4) | ✅ |
| 11 | tasks.py | `tts_single_task` 用 `_init_ctx` 替换 (T3) | ✅ |
| 12 | tasks.py | `music_task` 用 `_init_ctx` 替换 (T2) | ✅ |
| 13 | tasks.py | `ai_characters_task` / `ai_scenes_task` 用 `_init_ctx` + `_cfg_dir` 替换 (T1) | ✅ |
| 14 | tasks.py | `_load_episode_shots` 提取 + preview/produce 统一 (T6) | ✅ |
| 15 | app.js | `_loadEntityPage` 通用列表渲染 (J2) | ✅ |
| 16 | app.js | `_editEntityPanel` 通用编辑面板 (J1) | ✅ |

---

## 📋 待完成 — tasks.py

### ~~T1. `ai_characters_task` / `ai_scenes_task` 用 `_init_ctx` 替换~~ ✅
- 当前：每个函数 5 行 `_ensure_path + Config + Container + registered`
- 目标：`cfg, cont = _init_ctx(config_path)` 一行搞定
- 位置：line ~635, ~683

### ~~T2. `music_task` 用 `_init_ctx` 替换~~ ✅
- 当前：`_ensure_path()` + `from infra.config import Config` + `cfg = Config(...)`
- 位置：line ~522

### ~~T3. `tts_single_task` 用 `_init_ctx` 替换~~ ✅
- 当前：`_ensure_path()` + Config + Container + registered（6行）
- 位置：line ~498

### ~~T4. `_run_subtitle` 用 `_cfg_dir` 替换路径构建~~ ✅
- 当前：`from infra.config import Config; cfg = Config(...); Path(cfg.project_dir) / ...`
- 目标：`sb = _cfg_dir(config_path, "storyboard", "episodes.csv")`
- 位置：line ~475

### ~~T5. `_shot_dir` 用 `_cfg_dir` 替换~~ ✅
- 当前：`from infra.config import Config; return Path(Config(config_path).project_dir) / ...`
- 目标：`return _cfg_dir(config_path, "output", f"e{episode:02d}", f"s{shot_id}")`
- 位置：line ~49

### ~~T6. episode 级任务统一模式~~ ✅
- `preview_task` / `produce_task` 用 `_load_episode_shots` 统一加载+空检查
- 减少每个函数 1-2 行重复

---

## 📋 待完成 — api.py

### A1. `_active_project_dir()` 函数体中 `Path(active_file.read_text().strip())` 可简化
- 已经被 `_proj()` 替换，但函数本身可考虑用 `cached_property` 或模块级变量缓存
- 低优先级，每次请求都读文件性能可接受

### A2. `save_character` / `save_scene` 的 Pydantic → dict 转换重复
- `req.model_dump(exclude_none=True)` + `data.pop("id")` 重复两次
- 可提取 `_parse_entity(req)` 返回 `(entity_id, data)`
- 低优先级

---

## 📋 待完成 — app.js

### ~~J1. `editChar` / `editScene` 编辑面板结构重复~~ ✅
- 提取 `_editEntityPanel(type, id, cfg)` 通用编辑器
- 涵盖图片上传、表单构建、save/cancel

### ~~J2. `loadCharacters` / `loadScenes` 列表渲染重复~~ ✅
- 提取 `_loadEntityPage(type, cfg)` 通用列表渲染
- 涵盖卡片 grid、空状态引导、header 按钮

### J3. `newChar` / `newScene` 新建面板可合并
- 结构几乎相同，字段不同
- 低优先级

---

## 优先级排序

**高（立即可做，收益明显）：**
- T1, T2, T3, T4, T5 — tasks.py 用 `_init_ctx` / `_cfg_dir` 替换重复

**中（结构优化）：**
- T6 — episode 级任务统一
- J1, J2 — 前端实体管理统一

**低（锦上添花）：**
- A1, A2, J3

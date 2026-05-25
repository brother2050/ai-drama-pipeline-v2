# 🎬 AI 短剧全流程生产管线 v2

> 从剧本到成片，一键搞定 — 纯 Python，跨平台，零 Shell 脚本依赖

---

## ✨ 核心特性

| 特性 | 说明 |
|------|------|
| **纯 Python** | 零 Shell 脚本，Windows/macOS/Linux 通用 |
| **API 优先** | 所有三方工具通过 HTTP API 调用，无需本地 GPU |
| **Celery 异步** | Redis + Celery 任务队列，前端实时进度反馈 |
| **一键启动** | `drama serve` + `drama worker` |
| **DI 容器** | 后端自注册 + 按需创建 + 热重载 + 懒加载 |
| **人性化工作台** | 内联编辑、撤销重做、批量执行、资源预览 |
| **多语言界面** | 中文/English 双语支持 |
| **安全加固** | 输入校验、路径遍历防护、速率限制 |
| **96 项测试** | 集成测试 + Celery Mock + 前端 E2E |

---

## 🚀 快速开始

### 1. 克隆

```bash
git clone https://ghfast.top/https://github.com/brother2050/ai-drama-pipeline-v2.git
cd ai-drama-pipeline-v2
```

### 2. 安装依赖

```bash
# 基础安装（Web + Celery + TTS 云 API）
pip install -e .

# 含人脸检测（精确角色一致性检查）
pip install -e ".[face]"


# 全量安装
pip install -e ".[all]"
```

<details>
<summary>可选依赖详情</summary>

| 安装方式 | 包 | 用途 | 不装影响 |
|---------|---|------|---------|
| `.[face]` | numpy, insightface, onnxruntime | 精确人脸检测 | 回退到图片哈希 |
| `.[face]` | face_recognition | 次选人脸检测 | 回退到哈希 |
| `.[face]` | opencv-python-headless | 横转竖人脸定位 | 回退到模糊背景 |

不装可选包时，各功能自动降级，不会崩溃。

</details>

### 3. 启动 Redis + PostgreSQL（必选）

```bash
# Ubuntu
sudo apt install redis-server && sudo systemctl start redis
sudo apt install postgresql && sudo systemctl start postgresql

# macOS
brew install redis && brew services start redis
brew install postgresql && brew services start postgresql

# Docker
docker run -d -p 6379:6379 redis:7-alpine
docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=drama123 -e POSTGRES_USER=drama -e POSTGRES_DB=ai_drama postgres:16-alpine
```

### 4. 配置

```bash
cp .env.example .env
# 编辑 .env，必填:
#   AI_DRAMA_DB_DSN=postgresql://drama:drama123@127.0.0.1:5432/ai_drama
#   MIMO_API_KEY=（语音合成免费）
# 获取 MIMO_API_KEY: https://api.xiaomimimo.com
```

### 5. 启动

```bash
# 终端 1: 启动 Celery Worker（处理异步任务）
drama worker

# 终端 2: 启动 Web 工作台
drama serve

# 浏览器打开 http://localhost:8888
```

---

## 📖 CLI 命令

```bash
# 服务管理
drama serve                            # 启动 Web 工作台
drama worker                           # 启动 Celery Worker
drama worker -c 4                      # Worker 并发数 4
drama status                           # 服务状态（Redis + Celery + ComfyUI + TTS）
drama env                              # 环境信息（OS / Python / GPU / Redis）

# 🤖 AI 内容生成（需要 LLM 服务）
drama generate storyboard 1 --outline outline.txt   # 从大纲生成分镜表
drama generate storyboard 1 --text "林夏独自在家..."  # 直接输入大纲
drama generate storyboard 1 -o outline.md -d 120     # 指定时长 120 秒
drama generate characters -d "22岁温柔女生，长发" -d "25岁帅气男生"  # 生成角色
drama generate scenes -d "现代简约客厅，落地窗暖光" -d "繁华商业街"    # 生成场景
drama generate all 1 -o outline.txt                  # 一键全量生成

# 管线（通过 Celery 异步执行）
drama preview 1 draft                  # 快速预览（draft/standard/high）
drama produce 1                        # 完整生产
drama post 1 --vertical                # 后期合成 + 横转竖
drama all 1                            # 一键全流程（preview → produce → post）
drama portraits                        # 生成定妆照

# 项目管理
drama project list                     # 列出所有项目
drama project new love_story           # 创建新项目
drama project switch love_story        # 切换项目
drama project current                  # 显示当前项目
drama project delete love_story        # 删除项目（需确认）

# 清理
drama clean --logs                     # 清理日志
drama clean --cache                    # 清理缓存
```

---

## 🌐 Web 工作台

启动 `drama serve` 后访问 http://localhost:8888

| 页面 | 功能 |
|------|------|
| 📊 仪表盘 | 系统状态总览（Redis / Celery / ComfyUI / TTS / LipSync / LLM） |
| 👤 角色管理 | 创建/编辑/删除角色 + 🤖 AI 从描述生成 |
| 🏔️ 场景管理 | 创建/编辑/删除场景 + 🤖 AI 从描述生成 |
| 📝 分镜表 | 内联编辑表格 + 🤖 AI 从大纲一键生成 |
| 🎬 生产管线 | 按镜头逐步执行：TTS → 首帧 → 视频 → 口型同步 |
| 📂 项目管理 | 多项目切换 |
| ⚙️ 系统设置 | TTS/ComfyUI/LipSync/**LLM** 配置、语言切换 |

### 工作台快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+Z` | 撤销 |
| `Ctrl+Shift+Z` / `Ctrl+Y` | 重做 |
| `ESC` | 关闭弹窗/预览 |

---

## 📚 API 文档

启动 Web 工作台后访问：
- **Swagger UI**: http://localhost:8888/docs
- **ReDoc**: http://localhost:8888/redoc

---

## 🏗️ 架构

```
┌─────────────┐     POST /api/pipeline/run     ┌──────────────┐
│   Web 前端   │ ──────────────────────────────→ │   FastAPI    │
│  (内联编辑)   │ ←────────────────────────────── │   (提交任务)  │
│  撤销/重做    │     { task_id, poll_url }        └──────┬───────┘
│  批量执行     │                                         │
│  资源预览     │     GET /api/tasks/{id}                 │ .delay()
│             │ ──────────────────────→                 ▼
│             │ ←──────────────┐              ┌──────────────────┐
└─────────────┘   { progress } │              │  Celery + Redis  │
                               │              │  (任务队列)       │
                               │              └────────┬─────────┘
                               │                       │
                               │              ┌────────▼─────────┐
                               └──────────────│  Celery Worker   │
                                              │  TTS / ComfyUI   │
                                              │  LipSync / FFmpeg│
                                              └──────────────────┘
```

**流程**: Web 提交 → Redis 队列 → Worker 执行 → 实时更新进度 → 前端轮询展示

### 后端懒加载

后端模块按需加载，缺依赖自动跳过不崩溃：

```
api/__init__.py (懒加载)
  ├─ tts/mimo_voicedesign  → 需要 httpx + MIMO_API_KEY
  ├─ tts/mimo_voiceclone   → 需要 httpx + MIMO_API_KEY
  ├─ tts/gpt_sovits        → 需要 httpx + 本地服务
  ├─ tts/cosyvoice         → 需要 httpx + 本地服务
  ├─ tts/fish_speech       → 需要 httpx + 本地服务
  ├─ lipsync/musetalk      → 需要 httpx + 本地服务
  ├─ lipsync/wav2lip       → 需要 httpx + 本地服务
  ├─ image/comfyui         → 需要 httpx + ComfyUI
  ├─ video/animatediff     → 需要 ComfyUI
  ├─ llm/ollama            → 需要 httpx + Ollama
  └─ music/template        → 仅需 ffmpeg（无额外依赖）
```

### 一致性检测三级回退

```
insightface（精确） → face_recognition（次选） → 图片哈希（无依赖）
```

---

## ⚙️ 配置

编辑 `projects/<项目名>/config/project.yaml`：

```yaml
project:
  name: "我的短剧"
  episodes: 1
  fps: 24
  resolution: [1280, 720]
  style: "cinematic"
  genre: "urban"

comfyui:
  url: "http://127.0.0.1:8188"
  timeout: 300

models:
  tts_backend: "mimo-voicedesign"      # 云 API，开箱即用
  lip_sync_backend: "musetalk"
  music_backend: "template"            # ffmpeg 模板，无需额外服务
  image_backend: "sd15"
  video_backend: "animatediff"

  # 各后端配置
  musetalk:
    api_url: "http://your-musetalk-server:8080"
  gpt_sovits:
    api_url: "http://your-gpt-sovits-server:9880"

llm:
  enabled: false
  backend: "ollama"
  base_url: "http://localhost:11434"
  # model: "qwen3:8b"          # Ollama 模型名
  # api_key: ""                # OpenAI 兼容 API 需要

timeouts:
  comfyui: 300
  tts: 60
  lipsync: 120
  llm: 300
  music: 120
```

### LLM 配置示例

```yaml
# Ollama（本地）
llm:
  enabled: true
  backend: "ollama"
  base_url: "http://localhost:11434"
  model: "qwen3:8b"

# SiliconFlow（云 API）
llm:
  enabled: true
  backend: "openai"
  base_url: "https://api.siliconflow.cn"
  model: "Qwen/Qwen2.5-7B-Instruct"
  api_key: "sk-xxx"

# OpenAI
llm:
  enabled: true
  backend: "openai"
  base_url: "https://api.openai.com"
  model: "gpt-4o-mini"
  api_key: "sk-xxx"
```

配置加载支持：
- 默认值自动合并
- mtime 缓存（修改后自动重载）
- 必填字段校验
- 数值范围校验

---

## 🧪 测试

```bash
# 运行全部测试（96 项）
pytest tests/ -v

# 分类运行
pytest tests/test_all.py -v       # 基础功能（29 项）
pytest tests/test_api.py -v       # API 集成测试（32 项）
pytest tests/test_celery.py -v    # Celery 任务测试（15 项）
pytest tests/test_e2e.py -v       # 前端 E2E 测试（21 项）
```

---

## 📁 项目结构

```
ai-drama-pipeline-v2/
├── cli.py                    # 统一 CLI 入口（Click + Rich）
├── pyproject.toml            # 依赖与构建配置
├── .env.example              # 环境变量模板
│
├── api/                      # 后端层（懒加载 + DI 容器）
│   ├── __init__.py           # 懒加载注册
│   ├── registry.py           # 服务注册表 + Container
│   └── backends/             # TTS / LipSync / Image / Video / LLM / Music
│
├── pipeline/                 # Celery 异步任务
│   ├── celery_app.py         # Celery 配置 + 统一错误格式
│   └── tasks.py              # 每步独立任务 + 编排器
│
├── engines/                  # 引擎层
│   ├── prompt.py             # Prompt 构建 + 翻译
│   ├── workflow_builder.py   # ComfyUI 工作流构建
│   ├── consistency.py        # 角色一致性（三级回退）
│   ├── video_consistency.py  # 视频一致性检查
│   ├── storyboard.py         # 分镜表加载/验证
│   ├── llm_generator.py      # 🤖 LLM 内容生成（分镜/角色/场景）
│   ├── camera.py             # 机位/景别规范化
│   ├── emotions.py           # 情绪分析
│   ├── portrait.py           # 定妆照生成
│   ├── multi_char.py         # 多人同框
│   ├── quality.py            # 质量检查
│   ├── shot_manager.py       # 镜头管理器
│   ├── gpu_adapter.py        # GPU 自适应
│   └── workflow.py           # 工作流节点工具
│
├── post/                     # 后期处理
│   ├── subtitle.py           # SRT 字幕生成
│   ├── effects.py            # 调色/滤镜
│   ├── production.py         # 后期合成流水线
│   ├── vertical.py           # 横转竖（含人脸检测）
│   ├── music.py              # 配乐生成
│   └── distributor.py        # 多平台分发 + 兼容性检查
│
├── flow/                     # 编排层
│   ├── episode.py            # 集级状态管理
│   └── model_registry.py     # 模型注册表
│
├── infra/                    # 基础设施
│   ├── config.py             # 配置管理（缓存 + 校验）
│   ├── toolcheck.py          # 工具可用性检测（pipeline/web 共用）
│   ├── ffmpeg.py             # FFmpeg 封装
│   ├── transitions.py        # 转场拼接（精确 offset）
│   ├── gpu.py                # GPU 检测
│   ├── cache.py              # TTL 缓存
│   ├── retry.py              # 指数退避重试
│   ├── text.py               # 文本工具
│   ├── redis_mgr.py          # Redis 连接管理
│   └── database/             # PostgreSQL（必须）
│       ├── schema.py         # 表结构定义
│       ├── pool.py           # 连接池
│       ├── characters.py     # 角色 CRUD
│       ├── scenes.py         # 场景 CRUD
│       ├── episodes.py       # 集 CRUD
│       └── shots.py          # 镜头 CRUD
│
├── web/                      # FastAPI Web 工作台
│   ├── app.py                # 应用工厂 + 日志配置
│   ├── services/__init__.py  # 日志配置服务
│   ├── schemas/__init__.py   # Pydantic 请求模型
│   ├── routers/api.py        # API 路由（校验 + 防护）
│   └── static/               # 前端 SPA
│
├── scripts/                  # 工具脚本
│   └── project_mgr.py        # 项目管理（新建/切换/删除）
│
├── tests/                    # 测试
│   ├── test_all.py           # 基础功能测试
│   ├── test_api.py           # API 集成测试
│   ├── test_celery.py        # Celery 任务测试
│   └── test_e2e.py           # 前端 E2E 测试
│
├── config/                   # 全局配置
│   └── models_registry.yaml  # 模型注册表（后端定义）
│
├── workflows/                # ComfyUI 工作流模板（JSON）
│
└── projects/                 # 项目目录（每个短剧独立）
    ├── default/              # 默认项目模板
    │   ├── config/
    │   │   ├── project.yaml          # 项目配置
    │   │   ├── characters/*.yaml     # 角色配置
    │   │   └── scenes/*.yaml         # 场景配置
    │   ├── storyboard/
    │   │   └── episodes.csv          # 分镜剧本
    │   ├── assets/characters/        # 定妆照等角色素材
    │   ├── assets/scenes/            # 场景参考图
    │   ├── assets/loras/             # LoRA 模型文件
    │   ├── output/                   # 生成产物
    │   └── logs/                     # 项目日志
    └── <你的项目名>/         # 新建项目（结构同上）
```

---

## 🔒 安全

- **输入校验**: Pydantic 模型校验所有 API 请求（ID 格式、数值范围、文本长度）
- **路径遍历防护**: `_safe_path()` 阻断 `../` 攻击
- **速率限制**: 滑动窗口 60s/120 次
- **任务 ID 校验**: UUID 格式验证
- **配置校验**: 必填字段 + 数值范围 + 分辨率格式

---

## 📝 License

MIT

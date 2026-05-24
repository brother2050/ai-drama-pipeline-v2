# 🎬 AI 短剧全流程生产管线 v2

> 从剧本到成片，一键搞定 — 纯 Python，跨平台，零 Shell 依赖

---

## ✨ v2 核心特性

| 特性 | 说明 |
|------|------|
| **纯 Python** | 零 Shell 脚本，Windows/macOS/Linux 通用 |
| **API 优先** | 所有三方工具通过 HTTP API 调用，无需本地 GPU |
| **Celery 异步** | Redis + Celery 任务队列，前端实时进度反馈 |
| **一键启动** | `python cli.py serve` + `python cli.py worker` |
| **DI 容器** | 后端自注册 + 按需创建 + 热重载 |
| **Rich CLI** | 彩色终端输出，表格化状态展示 |

---

## 🚀 快速开始

### 1. 克隆

```bash
git clone https://ghfast.top/https://github.com/brother2050/ai-drama-pipeline-v2.git
cd ai-drama-pipeline-v2
```

### 2. 安装依赖

```bash
# 基础安装（Web + Celery + TTS）
pip install -e .

# 含人脸检测（精确角色一致性）
pip install -e ".[face]"

# 含 GPU 加速
pip install -e ".[gpu]"

# 全量安装
pip install -e ".[all]"
```

> 安装后 `drama` 命令即可用。如遇问题请确认 `pyproject.toml` 中 entry point 为 `cli:cli`。

#### 可选依赖说明

| 包 | 用途 | 不装影响 |
|---|------|---------|
| `numpy` | 人脸嵌入余弦相似度 | 一致性检测用纯 Python 回退 |
| `insightface` + `onnxruntime` | 精确人脸检测 | 回退到 face_recognition 或哈希 |
| `face_recognition` | 次选人脸检测 | 回退到哈希模式 |
| `opencv-python-headless` | 横转竖人脸定位 | 回退到模糊背景模式 |
| `torch` | GPU 检测加速 | CPU 模式运行 |
| `psycopg2-binary` | PostgreSQL 支持 | 使用 SQLite |

### 3. 启动 Redis（必选）

```bash
# Ubuntu
sudo apt install redis-server && sudo systemctl start redis

# macOS
brew install redis && brew services start redis

# Docker
docker run -d -p 6379:6379 redis:7-alpine
```

### 4. 配置

```bash
cp .env.example .env
# 编辑 .env，填入 MIMO_API_KEY（语音合成免费）
# 获取: https://api.xiaomimimo.com
```

### 5. 启动

```bash
# 终端 1: 启动 Celery Worker（处理异步任务）
python cli.py worker

# 终端 2: 启动 Web 工作台
python cli.py serve

# 浏览器打开 http://localhost:8888
```

---

## 📖 CLI 命令

```bash
# 服务
python cli.py serve                    # 启动 Web 工作台
python cli.py worker                   # 启动 Celery Worker
python cli.py status                   # 服务状态（Redis + Celery + ComfyUI）
python cli.py env                      # 环境信息

# 管线（通过 Celery 异步执行）
python cli.py preview 1 draft          # 快速预览
python cli.py produce 1                # 完整生产
python cli.py post 1 --vertical        # 后期合成+横转竖
python cli.py all 1                    # 一键全流程
python cli.py portraits                # 定妆照

# 项目
python cli.py project list             # 列出项目
python cli.py project new love_story   # 创建项目
python cli.py project switch love_story # 切换项目
python cli.py project current          # 当前项目
```

## 📚 API 文档

启动 Web 工作台后访问：
- **Swagger UI**: http://localhost:8888/docs
- **ReDoc**: http://localhost:8888/redoc

---

## 🏗️ 异步架构

```
┌─────────────┐     POST /api/pipeline/run     ┌──────────────┐
│   Web 前端   │ ──────────────────────────────→ │   FastAPI    │
│             │ ←────────────────────────────── │   (提交任务)  │
│             │     { task_id, poll_url }        └──────┬───────┘
│             │                                         │
│   轮询       │     GET /api/tasks/{id}                 │ .delay()
│   进度       │ ──────────────────────→                 ▼
│             │ ←──────────────┐              ┌──────────────────┐
└─────────────┘   { progress } │              │  Celery + Redis  │
                               │              │  (任务队列)       │
                               │              └────────┬─────────┘
                               │                       │
                               │              ┌────────▼─────────┐
                               └──────────────│  Celery Worker   │
                                              │  (AI 任务执行)    │
                                              │  TTS / ComfyUI   │
                                              │  LipSync / FFmpeg│
                                              └──────────────────┘
```

**流程**: Web 提交 → Redis 队列 → Worker 执行 → 实时更新进度 → 前端轮询展示

---

## ⚙️ 配置说明

编辑 `config/project.yaml`：

```yaml
comfyui:
  url: "https://your-comfyui-server:8188"  # 远程 ComfyUI

models:
  tts_backend: "mimo-voicedesign"  # 云 API，开箱即用
  lip_sync_backend: "musetalk"
  musetalk:
    api_url: "http://your-musetalk-server:8080"
```

---

## 📁 项目结构

```
ai-drama-pipeline-v2/
├── cli.py                 # 统一 CLI 入口
├── api/                   # 后端自注册 + DI 容器
│   ├── registry.py        # 服务注册表
│   └── backends/          # TTS / LipSync / Image / Video / LLM / Music
├── pipeline/              # Celery 异步任务
│   ├── celery_app.py      # Celery 配置
│   └── tasks.py           # 所有异步任务定义
├── engines/               # 引擎层（Prompt / 工作流 / 一致性）
├── post/                  # 后期（字幕 / 转场 / 配乐 / 横转竖）
├── flow/                  # 编排器 / 批量调度
├── infra/                 # 基础设施（Config / HTTP / FFmpeg / DB）
├── web/                   # FastAPI Web 工作台
│   ├── app.py             # 应用工厂
│   └── routers/api.py     # API 路由
├── config/                # 配置文件
└── storyboard/            # 分镜表
```

---

## 📝 License

MIT

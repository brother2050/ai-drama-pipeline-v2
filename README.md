# 🎬 AI 短剧全流程生产管线 v2

> 从剧本到成片，一键搞定 — 纯 Python，跨平台，零 Shell 依赖

---

## ✨ v2 核心特性

| 特性 | 说明 |
|------|------|
| **纯 Python** | 零 Shell 脚本，Windows/macOS/Linux 通用 |
| **API 优先** | 所有三方工具通过 HTTP API 调用，无需本地 GPU |
| **一键启动** | `python cli.py serve` 启动一切 |
| **自动依赖** | 启动时自动检测/启动 PostgreSQL、Redis |
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
pip install -e .
# 或最小安装
pip install fastapi uvicorn pyyaml python-dotenv httpx click rich Pillow
```

### 3. 配置

```bash
cp .env.example .env
# 编辑 .env，填入 MIMO_API_KEY（语音合成免费）
# 获取: https://api.xiaomimimo.com
```

### 4. 配置远程服务

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

### 5. 启动

```bash
python cli.py serve
# 浏览器打开 http://localhost:8888
```

---

## 📖 CLI 命令

```bash
# 服务
python cli.py serve                    # 启动 Web 工作台
python cli.py status                   # 服务状态
python cli.py setup                    # 环境检测
python cli.py worker                   # Celery Worker

# 管线
python cli.py preview 1 draft          # 快速预览
python cli.py produce 1                # 完整生产
python cli.py post 1                   # 后期合成
python cli.py post 1 --vertical        # 横转竖
python cli.py all 1                    # 一键全流程
python cli.py portraits                # 定妆照

# 项目
python cli.py project list             # 列出项目
python cli.py project new love_story   # 创建项目
python cli.py project switch love_story # 切换项目
python cli.py project current          # 当前项目

# 其他
python cli.py env                      # 环境信息
python cli.py clean --logs             # 清理日志
```

安装后可使用 `drama` 命令代替 `python cli.py`。

---

## 🏗️ 架构

```
cli.py (CLI 入口)
  │
  ├── api/                    # 后端服务层
  │   ├── registry.py         #   注册表 + DI 容器
  │   └── backends/           #   后端实现（纯 API 调用）
  │       ├── tts/            #     MiMo / GPT-SoVITS / CosyVoice
  │       ├── lipsync/        #     MuseTalk / SadTalker
  │       ├── image/          #     ComfyUI
  │       ├── llm/            #     Ollama / OpenAI
  │       └── music/          #     Template / MusicGen
  │
  ├── infra/                  # 基础设施
  │   ├── config.py           #     配置管理
  │   ├── http.py             #     HTTP 客户端
  │   ├── ffmpeg.py           #     FFmpeg 封装
  │   └── gpu.py              #     GPU 检测
  │
  ├── pipeline/               # 生产管线
  │   ├── preview.py          #     快速预览
  │   ├── producer.py         #     完整生产
  │   └── portraits.py        #     定妆照生成
  │
  ├── post/                   # 后期处理
  │   └── production.py       #     合成/字幕/转场/竖屏
  │
  └── web/                    # Web 工作台
      ├── app.py              #     FastAPI 工厂
      └── routers/api.py      #     API 路由
```

---

## 🔧 系统要求

| 模式 | GPU | 磁盘 | 适用 |
|------|-----|------|------|
| **API 模式**（推荐） | ❌ 不需要 | 2GB+ | 无 GPU 用户 |
| GPU 模式 | ✅ NVIDIA 16GB+ | 50GB+ | 有 GPU 用户 |

- Python 3.10+
- ffmpeg（音视频处理）
- PostgreSQL（可选，不配则跳过）
- Redis（可选，Celery 需要）

---

## 📄 许可证

MIT License

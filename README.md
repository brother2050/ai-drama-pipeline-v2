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
| **Seko 策划案** | 集成 seko.sensetime.com 影视策划案生成/修改 |
| **IP-Adapter Plus** | 基于 ip-adapter-plus-face 模型的角色面部一致性（SD1.5/SDXL 后端） |
| **PuLID-Flux** | 基于 PuLID 的 Flux 面部一致性（Flux 后端，推荐） |
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

# 含横转竖人脸追踪
pip install -e ".[vertical]"

# 全量安装
pip install -e ".[all]"
```

<details>
<summary>可选依赖详情</summary>

| 安装方式 | 包 | 用途 | 不装影响 |
|---------|---|------|---------|
| `.[vertical]` | face_recognition | 横转竖人脸追踪定位 | 回退到模糊背景 |
| `.[vertical]` | opencv-python-headless | 视频帧读取 | 回退到模糊背景 |

不装可选包时，各功能自动降级，不会崩溃。

</details>

### 3. 下载基础模型（按选择的后端）

> 项目启动前必须下载至少一个图像后端的基础模型。模型放到 `ComfyUI/models/` 对应子目录。

#### 📌 模型下载总览

| 后端 | UNet / Checkpoint | CLIP | VAE | 显存需求 |
|------|-------------------|------|-----|---------|
| **Cosmos（默认推荐）** | `cosmos_predict2_2B_t2i.safetensors` | `oldt5_xxl_fp8_e4m3fn_scaled.safetensors` | `wan_2.1_vae.safetensors` | ~12GB |
| **Flux** | `flux1-dev.safetensors` | `clip_l.safetensors` + `t5xxl_fp16.safetensors` | Flux 自带 | **≥32GB**（FP8 约 16GB） |
| **SD1.5** | `v1-5-pruned-emaonly.safetensors` | Checkpoint 自带 | Checkpoint 自带 | ~6GB |

> **GPU 兼容性速查**：
>
> | GPU | 显存 | 推荐后端 | 说明 |
> |-----|------|---------|------|
> | T4 | 16GB | Cosmos / SD1.5 | Flux fp8 可尝试，fp16 不行 |
> | A10 | 24GB | Cosmos / SD1.5 | Flux fp8 可尝试，fp16 不行 |
> | V100-32G | 32GB | Flux fp8 / Cosmos | Flux fp16 勉强，推荐 fp8 |
> | A100-40G | 40GB | Flux fp16 / Cosmos | 全部后端可用 |
> | A100-80G | 80GB | 全部 | 无限制 |

#### 方案 A：Cosmos 后端（推荐，12GB 显存即可）

```bash
# 1. UNet 模型 → ComfyUI/models/diffusion_models/
mkdir -p ComfyUI/models/diffusion_models/
wget -O ComfyUI/models/diffusion_models/cosmos_predict2_2B_t2i.safetensors \
  https://huggingface.co/nvidia/Cosmos-Predict2-2B-Text2Image/resolve/main/cosmos_predict2_2B_t2i.safetensors

# 2. CLIP 模型（T5-XXL FP8）→ ComfyUI/models/clip/
mkdir -p ComfyUI/models/clip/
wget -O ComfyUI/models/clip/oldt5_xxl_fp8_e4m3fn_scaled.safetensors \
  https://huggingface.co/nvidia/Cosmos-Predict2-2B-Text2Image/resolve/main/oldt5_xxl_fp8_e4m3fn_scaled.safetensors

# 3. VAE → ComfyUI/models/vae/
mkdir -p ComfyUI/models/vae/
wget -O ComfyUI/models/vae/wan_2.1_vae.safetensors \
  https://huggingface.co/nvidia/Cosmos-Predict2-2B-Text2Image/resolve/main/wan_2.1_vae.safetensors
```

> **Cosmos 视频生成**（可选，用于 `cosmos-video` 视频后端）：
> ```bash
> wget -O ComfyUI/models/diffusion_models/cosmos_predict2_2B_video2world_480p_16fps.safetensors \
>   https://huggingface.co/nvidia/Cosmos-Predict2-2B-Video2World/resolve/main/cosmos_predict2_2B_video2world_480p_16fps.safetensors
> ```

#### 方案 B：Flux 后端（≥32GB 显存）

```bash
# 1. UNet 模型 → ComfyUI/models/diffusion_models/（或 ComfyUI/models/unet/）
mkdir -p ComfyUI/models/diffusion_models/
wget -O ComfyUI/models/diffusion_models/flux1-dev.safetensors \
  https://huggingface.co/Comfy-Org/flux1-dev/resolve/main/flux1-dev.safetensors

# 2. CLIP 模型 → ComfyUI/models/clip/
mkdir -p ComfyUI/models/clip/
wget -O ComfyUI/models/clip/clip_l.safetensors \
  https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors
wget -O ComfyUI/models/clip/t5xxl_fp16.safetensors \
  https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors

# 3. VAE：Flux UNet 自带 VAE，无需单独下载
```

> **FP8 省显存版**（T4/A10 可尝试）：
> ```bash
> # 用 FP8 UNet 替代 FP16，显存从 32GB+ 降到 ~16GB
> # 注意：仍需 T4 (16GB) 级别以上，且生成速度较慢
> wget -O ComfyUI/models/diffusion_models/flux1-dev-fp8.safetensors \
>   https://huggingface.co/Kijai/flux-fp8/resolve/main/flux1-dev-fp8.safetensors
> ```

#### 方案 C：SD1.5 后端（≥6GB 显存，入门级）

```bash
# 1. Checkpoint 模型 → ComfyUI/models/checkpoints/
mkdir -p ComfyUI/models/checkpoints/
wget -O ComfyUI/models/checkpoints/v1-5-pruned-emaonly.safetensors \
  https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5/resolve/main/v1-5-pruned-emaonly.safetensors

# 2. AnimateDiff 运动模块（视频生成必须）→ ComfyUI/models/animatediff/
mkdir -p ComfyUI/models/animatediff/
wget -O ComfyUI/models/animatediff/mm_sd_v15_v2.ckpt \
  https://huggingface.co/guoyww/animatediff/resolve/main/mm_sd_v15_v2.ckpt
```

> SD1.5 的 CLIP 和 VAE 内嵌在 Checkpoint 中，无需单独下载。
> AnimateDiff 运动模块用于视频生成（`drama produce`），不装则无法生成镜头视频。

#### 📁 目录结构参考

```
ComfyUI/models/
├── diffusion_models/     # UNet 模型（Flux / Cosmos）
│   ├── flux1-dev.safetensors
│   └── cosmos_predict2_2B_t2i.safetensors
├── checkpoints/          # SD1.5 Checkpoint
│   └── v1-5-pruned-emaonly.safetensors
├── animatediff/          # AnimateDiff 运动模块（SD1.5 视频生成）
│   └── mm_sd_v15_v2.ckpt
├── clip/                 # 文本编码器
│   ├── clip_l.safetensors            # Flux
│   ├── t5xxl_fp16.safetensors        # Flux
│   └── oldt5_xxl_fp8_e4m3fn_scaled.safetensors  # Cosmos
├── vae/                  # VAE 解码器
│   └── wan_2.1_vae.safetensors       # Cosmos
├── ipadapter/            # IP-Adapter 模型（第 6 节）
├── pulid/                # PuLID-Flux 模型（第 7 节）
├── clip_vision/          # CLIP Vision 编码器
├── insightface/          # InsightFace 人脸模型
└── loras/                # LoRA 模型（训练产出）
```

### 4. 启动 Redis + PostgreSQL（必选）

```bash
# Ubuntu
sudo apt install redis-server && sudo systemctl start redis
sudo apt install postgresql && sudo systemctl start postgresql

# macOS
brew install redis && brew services start redis
brew install postgresql@16 && brew services start postgresql@16

# Docker
docker run -d -p 6379:6379 redis:7-alpine
docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=drama123 -e POSTGRES_USER=drama -e POSTGRES_DB=ai_drama postgres:16-alpine
```

#### 初始化数据库（Ubuntu / macOS 手动安装）

安装完成后，创建用户和数据库:

```bash
# 1. 创建 drama 用户（若尚不存在）
sudo -u postgres psql -c "CREATE USER drama WITH PASSWORD 'drama123';"

# 2. 创建 ai_drama 数据库（属主为 drama）
sudo -u postgres psql -c "CREATE DATABASE ai_drama OWNER drama;"

# 3. 授予 drama 用户建表权限
sudo -u postgres psql -c "GRANT ALL ON DATABASE ai_drama TO drama;"
```

> **macOS 注意**：Homebrew 安装后默认用户为系统用户名。若 `sudo -u postgres` 无效，可先用系统用户连接创建：
> ```bash
> psql -h 127.0.0.1 -U $(whoami) -d postgres -c "CREATE USER drama WITH PASSWORD 'drama123' SUPERUSER;"
> psql -h 127.0.0.1 -U $(whoami) -d postgres -c "CREATE DATABASE ai_drama OWNER drama;"
> ```

> **PostgreSQL 启动失败？（macOS 僵尸锁文件）**
>
> 若 `brew services` 显示 `error`，日志提示 `lock file "postmaster.pid" already exists`：
> ```bash
> # 检查是否有残留 postgres 进程
> ps aux | grep postgres | grep -v grep
> # 无运行进程则可安全删除锁文件
> rm /usr/local/var/postgresql@16/postmaster.pid
> # Apple Silicon 路径可能是 /opt/homebrew/var/postgresql@16/postmaster.pid
> # 重启服务
> brew services restart postgresql@16
> ```

### 5. 配置

```bash
cp .env.example .env
# 编辑 .env，必填:
#   AI_DRAMA_DB_DSN=postgresql://drama:drama123@127.0.0.1:5432/ai_drama
#   MIMO_API_KEY=（语音合成免费）
#   SEKO_API_KEY=（影视策划案，可选）
# 获取 MIMO_API_KEY: https://api.xiaomimimo.com
# 获取 SEKO_API_KEY: https://seko.sensetime.com/explore
```

### 6. 启动

```bash
# 终端 1: 启动 Celery Worker（处理异步任务）
drama worker

# 终端 2: 启动 Web 工作台
drama serve

# 浏览器打开 http://localhost:8888
```

> **并发数说明**：默认 concurrency=2，个人使用推荐 2-4。
>
> 主生产流程（`drama produce`）内部是逐镜头串行执行的，concurrency 设置不影响主流程速度。并发数主要影响 Web 工作台中多个操作同时提交时的响应（如同时生成定妆照和场景图）。外部服务（ComfyUI/TTS）通常是单实例单任务，设置过高的并发不会加速反而浪费内存。
>
> ```bash
> drama worker -c 2   # 默认，省资源
> drama worker -c 4   # Web 操作较多时推荐
> ```

### 7. IP-Adapter Plus（角色面部一致性，可选但强烈推荐）

> 基于 [ComfyUI_IPAdapter_plus](https://github.com/cubiq/ComfyUI_IPAdapter_plus) 实现跨镜头角色面部一致性。安装后定妆照的面部特征会通过 IP-Adapter 注入到每个镜头的首帧生成中，大幅提升同一角色在不同镜头间的辨识度。

#### ⚠️ 后端兼容性

| 图像后端 | 架构 | 可用一致性方案 | 说明 |
|---------|------|:-------------:|------|
| `flux` | DiT | **PuLID-Flux** | **推荐**，画质最佳 + 面部一致性强 |
| `sd15` | UNet | IP-Adapter Plus | 成熟稳定，面部一致性好 |
| `cosmos` | DiT | 无 | 仅 LoRA 训练 |

> 一致性方案与后端**独立配置**，通过 `consistency_method` 字段选择：

```yaml
# config/system.yaml
consistency_method: auto   # auto / pulid_flux / ip_adapter / none
#   auto:        根据 image_backend 自动选择（flux→pulid, sd15→ip_adapter, cosmos→none）
#   pulid_flux:  强制使用 PuLID-Flux（需 Flux 后端）
#   ip_adapter:  强制使用 IP-Adapter Plus（需 SD1.5/SDXL 后端）
#   none:        不使用一致性方案（仅靠 LoRA + seed）
```

#### 6.1 安装 ComfyUI 自定义节点

```bash
cd ComfyUI/custom_nodes/
git clone https://github.com/cubiq/ComfyUI_IPAdapter_plus.git
# 重启 ComfyUI
```

#### 6.2 下载模型文件

**方案 A：SD1.5 后端（推荐，IP-Adapter Plus 兼容）**

需要下载 **1 个 IP-Adapter 模型** + **1 个 CLIP Vision 编码器**：

```bash
# 1. IP-Adapter 模型 → 放入 ComfyUI/models/ipadapter/
#    目录不存在则手动创建: mkdir -p ComfyUI/models/ipadapter/
wget -O ComfyUI/models/ipadapter/ip-adapter-plus-face_sd15.safetensors \
  https://huggingface.co/h94/IP-Adapter/resolve/main/models/ip-adapter-plus-face_sd15.safetensors

# 2. CLIP Vision 编码器 → 放入 ComfyUI/models/clip_vision/
wget -O ComfyUI/models/clip_vision/CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors \
  https://huggingface.co/h94/IP-Adapter/resolve/main/models/image_encoder/model.safetensors
```

**方案 B：SDXL 后端**

```bash
# IP-Adapter 模型（SDXL 版）
wget -O ComfyUI/models/ipadapter/ip-adapter-plus-face_sdxl_vit-h.safetensors \
  https://huggingface.co/h94/IP-Adapter/resolve/main/sdxl_models/ip-adapter-plus-face_sdxl_vit-h.safetensors

# CLIP Vision 编码器（SDXL 用 bigG）
wget -O ComfyUI/models/clip_vision/CLIP-ViT-bigG-14-laion2B-39B-b160k.safetensors \
  https://huggingface.co/h94/IP-Adapter/resolve/main/sdxl_models/image_encoder/model.safetensors
```

<details>
<summary>全部可用模型</summary>

**SD1.5 系列**（CLIP Vision: `CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors`）

| 模型 | 说明 |
|------|------|
| `ip-adapter-plus-face_sd15.safetensors` | **默认推荐**，面部一致性最强 |
| `ip-adapter-plus_sd15.safetensors` | 通用 Plus，风格+内容保持 |
| `ip-adapter-full-face_sd15.safetensors` | 更强面部保持，可能过度拟合 |
| `ip-adapter_sd15.safetensors` | 基础模型，影响最弱 |

**SDXL 系列**（CLIP Vision: `CLIP-ViT-bigG-14-laion2B-39B-b160k.safetensors`）

| 模型 | 说明 |
|------|------|
| `ip-adapter-plus-face_sdxl_vit-h.safetensors` | SDXL 面部模型 |
| `ip-adapter-plus_sdxl_vit-h.safetensors` | SDXL 通用 Plus |
| `ip-adapter_sdxl.safetensors` | SDXL 基础（需 bigG 编码器） |

</details>

#### 6.3 配置

IP-Adapter 默认已启用，配置在 `config/system.yaml` 中：

```yaml
ip_adapter:
  enabled: true
  model: "ip-adapter-plus-face_sd15.safetensors"   # SD1.5 面部模型
  clip_vision: "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"
  weight: 0.75              # 参考图权重（官方建议 ≤0.8）
  secondary_weight: 0.45    # 多角色时次要角色权重
  embeds_scaling: "V only"  # 面部特征保持最佳的缩放模式
```

> 如使用 SDXL 后端，将 `model` 改为 `ip-adapter-plus-face_sdxl_vit-h.safetensors`，`clip_vision` 改为 `CLIP-ViT-bigG-14-laion2B-39B-b160k.safetensors`。

#### 6.4 验证

启动后在 Web 工作台仪表盘查看 IP-Adapter 状态，或 CLI：

```bash
drama status   # 应显示 IP-Adapter Plus ✅
```

### 8. PuLID-Flux（Flux 面部一致性，推荐）

> 基于 [PuLID](https://github.com/ToTheBeginning/PuLID) 的 Flux 面部一致性方案。通过 InsightFace 检测人脸 + EVA CLIP 编码面部特征，将 ID embedding 注入 Flux DiT 注意力层，实现跨镜头角色面部一致性。

#### 8.1 安装 ComfyUI 自定义节点

```bash
cd ComfyUI/custom_nodes/
git clone https://github.com/balazik/ComfyUI-PuLID-Flux.git
# 可选增强版（更多融合方法）：
# git clone https://github.com/sipie800/ComfyUI-PuLID-Flux-Enhanced.git
# 重启 ComfyUI
```

#### 8.2 下载模型文件

需要下载 **3 类模型**：

```bash
# 1. PuLID Flux 模型 → ComfyUI/models/pulid/
mkdir -p ComfyUI/models/pulid/
wget -O ComfyUI/models/pulid/pulid_flux_v0.9.0.safetensors \
  "https://huggingface.co/guozinan/PuLID/resolve/main/pulid_flux_v0.9.0.safetensors"

# 2. InsightFace AntelopeV2（5 个文件）→ ComfyUI/models/insightface/models/antelopev2/
mkdir -p ComfyUI/models/insightface/models/antelopev2/
# 从 https://huggingface.co/MonsterMMORPG/tools/tree/main 下载后解压到此目录

# 3. EVA02-CLIP-L-14-336 → 首次运行自动下载（或手动放到 ComfyUI/models/clip/）
```

#### 8.3 配置

PuLID-Flux 默认已启用，配置在 `config/system.yaml` 中：

```yaml
pulid_flux:
  enabled: true
  model: "pulid_flux_v0.9.0.safetensors"
  weight: 0.9              # 推荐 0.8-0.95（1.0 过拟合）
  fusion: "mean"           # 多图融合方法: mean / concat / max / train_weight
  use_gray: true           # 灰度优化（边缘轮廓更自然）
```

#### 8.4 技巧

- **参考图质量很重要**：使用清晰、正面、光线均匀的定妆照
- **weight 推荐 0.8-0.95**：1.0 容易过拟合，面部僵硬
- **Euler + simple** 调度器始终可用；Euler + beta 对低质量参考图效果更好
- **多角色同框**：自动链式注入，主角色 weight=0.9，次要角色自动降权

### 三阶段架构（推荐工作流）

```
阶段1: drama prepare 1     ← LLM 密集，运行一次
  ├─ 批量翻译角色/场景/分镜 → 写入 YAML *_en 字段
  ├─ 定妆照 → Web 工作台「📸 定妆照」单独执行
  └─ 场景图 → Web 工作台「🏔️ 场景图」单独执行

阶段2: drama produce 1     ← 纯 GPU/本地，零 LLM 调用，全速
  ├─ TTS → 首帧 → 视频 → 口型同步
  └─ 直接读取预翻译字段，不等待 LLM

阶段3: drama post 1        ← 纯本地
  └─ 拼接 → 字幕 → 配乐 → 横转竖
```

**收益**: prepare 跑完后，produce 完全不依赖 LLM，10 个镜头从 30-40 次 LLM 调用降为 0 次。

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
drama prepare 1                        # 准备阶段（批量翻译）
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
| ⚙️ 系统设置 | TTS/ComfyUI/LipSync/**LLM**/**Seko** 配置、语言切换 |

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
  batch_translate: true         # 批量翻译（多条合并一次 LLM 调用，false 则逐条翻译）

portraits:
  auto_outfit: true             # 管线中自动生成 outfit 参考图（默认 true）

timeouts:
  comfyui: 300
  tts: 60
  lipsync: 120
  llm: 300
  music: 120

seko:
  # api_key: ''  # 或设置环境变量 SEKO_API_KEY
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

本项目面向**个人本地使用**，安全措施以实用为主，不做过度防护。

已有的安全机制：
- **输入校验**: Pydantic 模型校验 API 请求（ID 格式、数值范围、文本长度）
- **路径遍历防护**: `_safe_path()` 阻断 `../` 攻击
- **任务 ID 校验**: UUID 格式验证

> 个人部署场景下，速率限制（60s/120 次）等功能不构成实际需求。如需暴露到公网，请自行在前端加 Nginx 反向代理并配置认证。

---

## 📝 License

MIT

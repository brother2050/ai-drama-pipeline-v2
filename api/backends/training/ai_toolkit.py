"""AI Toolkit 训练后端 — 通过原生 Web UI API 远程调用 ostris/ai-toolkit 训练 LoRA

AI Toolkit 是 Flux LoRA 训练质量最好的开源工具，原生支持量化训练（12GB 可跑）。

部署方式:
  1. 在 GPU 服务器上安装 AI Toolkit:
     git clone https://github.com/ostris/ai-toolkit.git
     cd ai-toolkit && git checkout next && pip install -r requirements.txt

  2. 启动 Web UI:
     python run.py --ui
     （默认运行在 http://localhost:8675）

  3. 配置 config/system.yaml:
     training:
       backend: ai-toolkit
       api_url: http://<gpu-server>:8675

API 使用 AI Toolkit 原生 Next.js API（v0.9.14+）:
  POST /api/datasets/create   — 创建数据集
  POST /api/datasets/upload   — 上传图片到数据集
  POST /api/jobs              — 创建训练作业
  GET  /api/jobs/<id>/start   — 启动作业
  GET  /api/jobs?id=<id>      — 查询作业状态
  GET  /api/jobs/<id>/log     — 查看作业日志
  GET  /api/settings          — 获取服务端设置
  GET  /api/gpu               — GPU 状态

LoRA 文件命名规范:
  训练完成后，将 .safetensors 文件放入项目的 assets/loras/ 目录，
  文件名必须为: {char_id}_lora.safetensors
  例如: ch_8a3f2b1c_lora.safetensors

  项目查找 LoRA 的优先级:
    1. proj_{hash8}_{char_id}_{char_id}_lora.safetensors  （comfyui_asset_name 生成）
    2. {char_id}_lora.safetensors
    3. {char_id}.safetensors
    4. assets/characters/{char_id}/lora/*.safetensors
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

from api.registry import BackendMeta, registry

logger = logging.getLogger(__name__)

__all__ = ["AIToolkitTrainer"]

MAX_IMAGES = 150


class AIToolkitTrainer:
    """AI Toolkit 远程 LoRA 训练后端（原生 API）"""

    def __init__(self, config: dict):
        self._api_url = (config.get("api_url")
                         or config.get("training", {}).get("api_url", "")
                         or "http://127.0.0.1:8675")
        self._api_key = (config.get("api_key")
                         or config.get("training", {}).get("api_key", "")
                         or os.environ.get("AI_TOOLKIT_API_KEY", ""))
        self._gpu_ids = str(config.get("gpu_ids")
                            or config.get("training", {}).get("gpu_ids", "0"))
        self._timeout = config.get("timeout", 3600)
        self._poll_interval = config.get("poll_interval", 10)
        self._project_dir = (config.get("project_dir")
                             or config.get("_project_dir") or "")
        if not self._project_dir:
            logger.warning("AIToolkitTrainer: project_dir 为空，下载结果可能失败")

        # 训练参数默认值
        defaults = config.get("defaults", {})
        self._default_resolution = self._parse_resolution(
            defaults.get("resolution", 512))
        self._default_learning_rate = str(defaults.get("learning_rate", "1e-4"))
        self._default_network_dim = int(defaults.get("network_dim", 16))
        self._default_conv_dim = int(defaults.get("conv_dim", 16))
        self._default_steps = int(defaults.get("steps", 1000))
        self._base_model = str(defaults.get("base_model", "black-forest-labs/FLUX.1-dev"))
        self._arch = str(defaults.get("arch", ""))
        self._quantize_type = str(defaults.get("quantize_type", "qfloat8"))
        self._timestep_type = str(defaults.get("timestep_type", "sigmoid"))
        self._save_format = str(defaults.get("save_format", "diffusers"))
        self._use_ema = bool(defaults.get("use_ema", False))

    @property
    def name(self) -> str:
        return "ai-toolkit"

    def _headers(self) -> dict:
        """JSON 请求 headers"""
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _auth_headers(self) -> dict:
        """仅含认证的 headers（用于 multipart 等非 JSON 请求）"""
        if self._api_key:
            return {"Authorization": f"Bearer {self._api_key}"}
        return {}

    def _collect_images(self, images_dir: str) -> list[str]:
        """收集目录中的图片文件路径，最多 MAX_IMAGES 张"""
        img_dir = Path(images_dir)
        if not img_dir.exists():
            return []
        paths = []
        for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
            paths.extend(str(p) for p in img_dir.glob(ext))
        # 也收集子目录（如 outfit 子目录）
        for sub in img_dir.iterdir():
            if sub.is_dir():
                for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
                    paths.extend(str(p) for p in sub.glob(ext))
        paths.sort()
        return paths[:MAX_IMAGES]

    def _validate_paths(self, img_paths: list[str]) -> list[str]:
        """验证图片路径有效性"""
        valid = []
        for p in img_paths:
            if not p:
                continue
            try:
                if Path(p).exists():
                    valid.append(p)
                else:
                    logger.warning(f"  跳过不存在的图片: {p}")
            except (TypeError, OSError) as e:
                logger.warning(f"  跳过无效路径 {p}: {e}")
        return valid

    @staticmethod
    def _parse_resolution(resolution: str | int) -> int:
        """解析分辨率: 512, "512", "512x768" → 512"""
        if isinstance(resolution, int):
            return resolution
        try:
            return int(str(resolution).split("x")[0])
        except (ValueError, AttributeError):
            return 512

    # ────────────────────────────────────────────────
    # 原生 API 调用
    # ────────────────────────────────────────────────

    def _api_get_settings(self) -> dict:
        """GET /api/settings — 获取服务端设置（训练目录、数据集目录）"""
        import httpx
        url = f"{self._api_url.rstrip('/')}/api/settings"
        resp = httpx.get(url, headers=self._headers(), timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _api_get_gpu(self) -> dict:
        """GET /api/gpu — 获取 GPU 状态"""
        import httpx
        url = f"{self._api_url.rstrip('/')}/api/gpu"
        resp = httpx.get(url, headers=self._headers(), timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _api_create_dataset(self, name: str) -> str:
        """POST /api/datasets/create — 创建数据集，返回清理后的名称"""
        import httpx
        url = f"{self._api_url.rstrip('/')}/api/datasets/create"
        resp = httpx.post(url, json={"name": name},
                          headers=self._headers(), timeout=30)
        resp.raise_for_status()
        result = resp.json()
        if result.get("error"):
            raise RuntimeError(f"创建数据集失败: {result['error']}")
        return result.get("name", name)

    def _api_upload_images(self, dataset_name: str, img_paths: list[str]) -> list[str]:
        """POST /api/datasets/upload — 上传图片到数据集

        Args:
            dataset_name: 数据集名称（已清理）
            img_paths: 图片文件路径列表

        Returns:
            上传成功的文件名列表
        """
        import httpx

        url = f"{self._api_url.rstrip('/')}/api/datasets/upload"

        # 构建 multipart 文件
        files = []
        for p in img_paths:
            files.append(("files", (Path(p).name, open(p, "rb"), "image/png")))

        data = {"datasetName": dataset_name}

        try:
            resp = httpx.post(url, files=files, data=data,
                              headers=self._auth_headers(),
                              timeout=120)
            resp.raise_for_status()
            result = resp.json()
            if result.get("error"):
                raise RuntimeError(f"上传图片失败: {result['error']}")
            return result.get("files", [])
        finally:
            # 确保文件句柄关闭
            for _, (_, fh, _) in files:
                if hasattr(fh, "close"):
                    fh.close()

    def _api_create_job(self, name: str, job_config: dict) -> dict:
        """POST /api/jobs — 创建训练作业

        Args:
            name: 作业名称
            job_config: AI Toolkit 配置（YAML 结构转为 dict）

        Returns:
            作业对象（含 id 字段）
        """
        import httpx
        url = f"{self._api_url.rstrip('/')}/api/jobs"
        body = {
            "name": name,
            "gpu_ids": self._gpu_ids,
            "job_config": job_config,
            "job_type": "train",
        }
        resp = httpx.post(url, json=body,
                          headers=self._headers(), timeout=30)
        resp.raise_for_status()
        result = resp.json()
        if result.get("error"):
            raise RuntimeError(f"创建作业失败: {result['error']}")
        return result

    def _api_start_job(self, job_id: str) -> dict:
        """GET /api/jobs/<id>/start — 启动作业（加入队列）"""
        import httpx
        url = f"{self._api_url.rstrip('/')}/api/jobs/{job_id}/start"
        resp = httpx.get(url, headers=self._headers(), timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _api_get_job(self, job_id: str) -> dict:
        """GET /api/jobs?id=<id> — 查询单个作业状态"""
        import httpx
        url = f"{self._api_url.rstrip('/')}/api/jobs"
        resp = httpx.get(url, params={"id": job_id},
                         headers=self._headers(), timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _api_get_job_log(self, job_id: str) -> str:
        """GET /api/jobs/<id>/log — 获取作业日志"""
        import httpx
        url = f"{self._api_url.rstrip('/')}/api/jobs/{job_id}/log"
        resp = httpx.get(url, headers=self._headers(), timeout=10)
        resp.raise_for_status()
        result = resp.json()
        return result.get("log", "")

    def _api_stop_job(self, job_id: str) -> dict:
        """GET /api/jobs/<id>/stop — 停止作业"""
        import httpx
        url = f"{self._api_url.rstrip('/')}/api/jobs/{job_id}/stop"
        resp = httpx.get(url, headers=self._headers(), timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _api_delete_job(self, job_id: str) -> dict:
        """GET /api/jobs/<id>/delete — 删除作业"""
        import httpx
        url = f"{self._api_url.rstrip('/')}/api/jobs/{job_id}/delete"
        resp = httpx.get(url, headers=self._headers(), timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _api_list_datasets(self) -> list:
        """GET /api/datasets/list — 列出数据集"""
        import httpx
        url = f"{self._api_url.rstrip('/')}/api/datasets/list"
        resp = httpx.get(url, headers=self._headers(), timeout=10)
        resp.raise_for_status()
        return resp.json()

    # ────────────────────────────────────────────────
    # 配置构建
    # ────────────────────────────────────────────────

    def _build_job_config(self, dataset_name: str, trigger_word: str,
                          lora_name: str, steps: int, learning_rate: str,
                          rank: int, resolution: int,
                          conv_rank: int = 0,
                          sample_prompts: list[str] | None = None) -> dict:
        """构建 AI Toolkit 训练配置（与 Web UI 的 New Job 表单一致）

        支持 Flex.1-alpha / FLUX.1-dev 等模型，自动适配 arch、量化、conv LoRA 等。

        Returns:
            AI Toolkit YAML 配置结构（dict），可直接作为 job_config 提交
        """
        # Conv LoRA：rank > 0 时启用
        network_cfg: dict[str, Any] = {
            "type": "lora",
            "linear": rank,
            "linear_alpha": rank,
        }
        if conv_rank > 0:
            network_cfg["conv"] = conv_rank
            network_cfg["conv_alpha"] = conv_rank

        # 模型配置：区分 Flex.1 vs FLUX.1
        model_cfg: dict[str, Any] = {
            "name_or_path": self._base_model,
            "quantize": True,
            "qtype": self._quantize_type,
            "quantize_te": True,
            "qtype_te": self._quantize_type,
        }
        # 自动检测 arch（Flex.1-alpha → flex1，FLUX.1-dev → flux）
        arch = self._arch
        if not arch:
            if "flex" in self._base_model.lower():
                arch = "flex1"
            else:
                arch = "flux"
        model_cfg["arch"] = arch
        # Flex.1 需要 bypass_guidance_embedding
        is_flex = arch == "flex1"

        # 采样 prompt 列表
        if not sample_prompts:
            sample_prompts = [
                f"{trigger_word} portrait, cinematic lighting",
                f"{trigger_word} casual outfit, outdoor",
                f"{trigger_word} close-up, studio lighting",
            ]
        samples = [{"prompt": p} for p in sample_prompts]

        # 多桶分辨率：单值 → 三档相同；数组 → 原样使用
        if isinstance(resolution, int):
            res_buckets = [resolution, resolution, resolution]
        else:
            res_buckets = list(resolution) if resolution else [512, 768, 1024]

        return {
            "job": "extension",
            "config": {
                "name": lora_name,
                "process": [{
                    "type": "diffusion_trainer",
                    "training_folder": "output",
                    "device": "cuda:0",
                    "trigger_word": trigger_word,
                    "network": network_cfg,
                    "save": {
                        "dtype": "bf16",
                        "save_every": max(1, steps // 4),
                        "max_step_saves_to_keep": 4,
                        "save_format": self._save_format,
                    },
                    "datasets": [{
                        "folder_path": dataset_name,
                        "caption_ext": "txt",
                        "caption_dropout_rate": 0.05,
                        "shuffle_tokens": False,
                        "cache_latents_to_disk": True,
                        "resolution": res_buckets,
                    }],
                    "train": {
                        "batch_size": 1,
                        "steps": steps,
                        "gradient_accumulation_steps": 1,
                        "train_unet": True,
                        "train_text_encoder": False,
                        "gradient_checkpointing": True,
                        "noise_scheduler": "flowmatch",
                        "optimizer": "adamw8bit",
                        "timestep_type": self._timestep_type,
                        "optimizer_params": {"weight_decay": 0.0001},
                        "lr": float(learning_rate),
                        "ema_config": {"use_ema": self._use_ema, "ema_decay": 0.99},
                        "dtype": "bf16",
                        "loss_type": "mse",
                        "bypass_guidance_embedding": is_flex,
                    },
                    "model": model_cfg,
                    "sample": {
                        "sampler": "flowmatch",
                        "sample_every": max(1, steps // 4),
                        "width": res_buckets[0],
                        "height": res_buckets[1],
                        "samples": samples,
                        "neg": "",
                        "seed": 42,
                        "walk_seed": True,
                        "guidance_scale": 4,
                        "sample_steps": 30,
                    },
                    "logging": {
                        "log_every": 1,
                        "use_ui_logger": True,
                    },
                }],
            },
        }

    # ────────────────────────────────────────────────
    # 主入口
    # ────────────────────────────────────────────────

    def train_lora(self, char_id: str, images_dir: str, *,
                   trigger_word: str = "",
                   steps: int = 600,
                   learning_rate: float = 1e-4,
                   rank: int = 16,
                   resolution: str = "512x768",
                   output_name: str = "") -> str:
        """训练角色 LoRA

        Args:
            char_id: 角色 ID
            images_dir: 训练图片目录
            trigger_word: 触发词
            steps: 训练步数
            learning_rate: 学习率
            rank: LoRA rank (network_dim)
            resolution: 训练分辨率
            output_name: 输出文件名（默认 {char_id}_lora）

        Returns:
            本地 .safetensors 路径
        """
        if not output_name:
            output_name = f"{char_id}_lora"
        if not trigger_word:
            trigger_word = f"ohwx {char_id}"

        res_val = self._parse_resolution(resolution)
        lr_str = str(learning_rate) if isinstance(learning_rate, float) else learning_rate

        # 收集 + 验证图片
        img_paths = self._collect_images(images_dir)
        img_paths = self._validate_paths(img_paths)
        if not img_paths:
            raise FileNotFoundError(f"训练图片目录中无有效图片: {images_dir}")

        logger.info(f"开始训练 LoRA: {char_id}, 图片 {len(img_paths)} 张, "
                    f"steps={steps}, rank={rank}, resolution={res_val}")

        # ── 1. 创建数据集并上传图片 ──
        dataset_name = f"lora_{char_id}_{int(time.time())}"
        try:
            dataset_name = self._api_create_dataset(dataset_name)
            logger.info(f"  数据集已创建: {dataset_name}")
        except Exception as e:
            raise ConnectionError(f"创建数据集失败: {e}")

        try:
            uploaded = self._api_upload_images(dataset_name, img_paths)
            logger.info(f"  已上传 {len(uploaded)} 张图片到数据集 {dataset_name}")
        except Exception as e:
            raise ConnectionError(f"上传图片失败: {e}")

        # ── 2. 生成 caption 文件（每张图一个 .txt）──
        # AI Toolkit 数据集需要 caption 文件与图片同目录
        # 通过上传 caption 文件实现
        caption_files = []
        for p in img_paths:
            cap_path = Path(p).with_suffix(".txt")
            if not cap_path.exists():
                cap_path.write_text(trigger_word, encoding="utf-8")
                caption_files.append(str(cap_path))

        if caption_files:
            try:
                self._api_upload_images(dataset_name, caption_files)
                logger.info(f"  已上传 {len(caption_files)} 个 caption 文件")
            except Exception as e:
                logger.warning(f"  caption 文件上传失败: {e}")

        # ── 3. 构建训练配置 ──
        job_config = self._build_job_config(
            dataset_name, trigger_word, output_name,
            steps, lr_str, rank, res_val,
            conv_rank=self._default_conv_dim,
        )

        # ── 4. 创建训练作业 ──
        job_name = f"lora_{char_id}_{int(time.time())}"
        try:
            job = self._api_create_job(job_name, job_config)
            job_id = job.get("id", "")
            if not job_id:
                raise RuntimeError(f"API 未返回作业 ID: {job}")
            logger.info(f"  训练作业已创建: {job_id}")
        except Exception as e:
            raise ConnectionError(f"创建训练作业失败: {e}")

        # ── 5. 启动作业 ──
        try:
            self._api_start_job(job_id)
            logger.info(f"  训练作业已加入队列: {job_id}")
        except Exception as e:
            raise ConnectionError(f"启动训练作业失败: {e}")

        # ── 6. 轮询等待完成 ──
        start_time = time.time()
        last_status = ""
        last_step = 0
        while True:
            if time.time() - start_time > self._timeout:
                raise TimeoutError(f"训练超时（{self._timeout}s）: {job_id}")

            try:
                job_data = self._api_get_job(job_id)
            except Exception as e:
                logger.warning(f"  查询作业状态失败: {e}")
                time.sleep(self._poll_interval)
                continue

            if not job_data or isinstance(job_data, list):
                logger.warning(f"  作业数据异常: {job_data}")
                time.sleep(self._poll_interval)
                continue

            status = job_data.get("status", "unknown")
            step = job_data.get("step", 0)
            info = job_data.get("info", "")

            if status != last_status or step != last_step:
                logger.info(f"  训练状态: {status}, step={step}, info={info}")
                last_status = status
                last_step = step

            if status in ("done", "complete", "finished"):
                logger.info(f"  训练完成: {info}")
                break
            elif status in ("error", "failed"):
                # 获取详细日志
                try:
                    log = self._api_get_job_log(job_id)
                    if log:
                        logger.error(f"  训练日志:\n{log[-2000:]}")
                except Exception:
                    pass
                raise RuntimeError(f"训练失败: {info}")
            elif status in ("stopped", "cancelled"):
                raise RuntimeError(f"训练被取消: {info}")

            time.sleep(self._poll_interval)

        # ── 7. 获取结果 ──
        # 训练完成后，结果文件在服务端的训练目录中
        # 需要通过 API 获取文件或让用户手动复制
        settings = {}
        try:
            settings = self._api_get_settings()
        except Exception:
            pass

        training_folder = settings.get("TRAINING_FOLDER", "/tmp/ai_toolkit_output")

        # 获取作业日志以查找输出文件路径
        output_dir = Path(self._project_dir) / "assets" / "loras"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(output_dir / f"{output_name}.safetensors")

        # 尝试从作业信息中获取结果路径
        result_found = False
        try:
            log = self._api_get_job_log(job_id)
            if log:
                # 解析日志查找 .safetensors 文件路径
                import re
                for line in reversed(log.split("\n")):
                    match = re.search(r"([\w/\\]+\.safetensors)", line)
                    if match:
                        remote_path = match.group(1)
                        logger.info(f"  发现训练产物: {remote_path}")
                        # 尝试通过 files API 下载
                        try:
                            self._download_result(remote_path, output_path)
                            result_found = True
                            break
                        except Exception as e:
                            logger.warning(f"  下载失败: {e}")
        except Exception:
            pass

        if not result_found:
            # 回退：尝试从标准输出目录查找
            job_output_dir = Path(training_folder) / job_name / "output"
            remote_candidates = [
                str(job_output_dir / f"{output_name}.safetensors"),
                str(job_output_dir / "lora.safetensors"),
            ]
            for candidate in remote_candidates:
                try:
                    self._download_result(candidate, output_path)
                    result_found = True
                    break
                except Exception:
                    continue

        if not result_found:
            raise RuntimeError(
                f"训练完成但无法自动获取结果文件。\n"
                f"请手动将 .safetensors 从服务器复制到: {output_path}\n"
                f"服务端训练目录: {training_folder}/{job_name}/output/\n"
                f"文件名必须为: {output_name}.safetensors")

        logger.info(f"LoRA 已保存: {output_path}")
        return output_path

    def _download_result(self, remote_path: str, local_path: str) -> str:
        """通过 files API 下载训练结果"""
        import httpx

        url = f"{self._api_url.rstrip('/')}/api/files/{remote_path}"
        resp = httpx.get(url, headers=self._auth_headers(),
                         timeout=300, follow_redirects=True)
        resp.raise_for_status()

        # 检查是否为有效文件（非 HTML 错误页面）
        content_type = resp.headers.get("content-type", "")
        if "text/html" in content_type:
            raise RuntimeError(f"服务端返回 HTML 而非文件: {remote_path}")

        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(resp.content)

        return local_path

    # ────────────────────────────────────────────────
    # 状态查询
    # ────────────────────────────────────────────────

    def check_status(self) -> dict:
        """检查 AI Toolkit 服务状态"""
        import httpx
        try:
            # 尝试获取 GPU 信息来验证连接
            url = f"{self._api_url.rstrip('/')}/api/gpu"
            resp = httpx.get(url, headers=self._headers(), timeout=5)
            data = resp.json() if resp.status_code == 200 else {}

            gpus = data.get("gpus", [])
            gpu_info = ""
            if gpus:
                gpu = gpus[0]
                gpu_info = f"{gpu.get('name', '?')} ({gpu.get('memory', {}).get('total', 0)}MB)"

            return {
                "status": "connected",
                "url": self._api_url,
                "message": f"AI Toolkit 就绪 — {gpu_info}",
                "gpu": gpu_info,
            }
        except httpx.ConnectError:
            return {"status": "disconnected", "url": self._api_url,
                    "error": "连接被拒绝"}
        except httpx.TimeoutException:
            return {"status": "disconnected", "url": self._api_url,
                    "error": "连接超时"}
        except Exception as e:
            return {"status": "disconnected", "url": self._api_url,
                    "error": str(e)}

    def shutdown(self):
        pass


# ── 注册 ──

registry.register(BackendMeta(
    name="ai-toolkit",
    service_type="training",
    factory=lambda cfg: AIToolkitTrainer(cfg),
    description="AI Toolkit 远程 LoRA 训练（原生 Web API，Flux 原生优化）",
    priority=10,
    tags=["lora", "training", "ai-toolkit", "flux", "ostris"],
))

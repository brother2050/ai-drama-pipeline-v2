"""kohya-ss 训练后端 — 通过 REST API 远程调用 kohya-ss sd-scripts 训练 LoRA

支持两种部署方式:
  1. 用户自建 REST API 包装 kohya-ss sd-scripts（推荐）
  2. 直接调用 kohya-ss Gradio Web UI（需 gradio_client）

REST API 约定:
  POST /train         — 启动训练（multipart: images + json params）
  GET  /status/{id}   — 查询训练状态
  GET  /result/{id}   — 下载训练结果（.safetensors）

LoRA 文件命名规范:
  训练完成后，将 .safetensors 文件放入项目的 assets/loras/ 目录，
  文件名必须为: {char_id}_lora.safetensors
  例如: ch_8a3f2b1c_lora.safetensors

  项目查找 LoRA 的优先级:
    1. proj_{hash8}_{char_id}_{char_id}_lora.safetensors  （comfyui_asset_name 生成）
    2. {char_id}.safetensors
    3. assets/characters/{char_id}/lora/*.safetensors
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from api.registry import BackendMeta, registry

logger = logging.getLogger(__name__)

__all__ = ["KohyaSSTrainer"]

MAX_IMAGES = 150


class KohyaSSTrainer:
    """kohya-ss 远程 LoRA 训练后端"""

    def __init__(self, config: dict):
        self._api_url = (config.get("api_url")
                         or config.get("training", {}).get("api_url", "")
                         or "http://127.0.0.1:7860")
        self._api_key = (config.get("api_key")
                         or config.get("training", {}).get("api_key", ""))
        self._timeout = config.get("timeout", 3600)
        self._poll_interval = config.get("poll_interval", 10)
        self._project_dir = (config.get("project_dir")
                             or config.get("_project_dir") or "")
        if not self._project_dir:
            logger.warning("KohyaSSTrainer: project_dir 为空，下载结果可能失败")

        # 训练参数默认值
        defaults = config.get("defaults", {})
        self._default_resolution = self._parse_resolution(
            defaults.get("resolution", 512))
        self._default_learning_rate = str(defaults.get("learning_rate", "8e-4"))
        self._default_network_dim = int(defaults.get("network_dim", 4))
        self._default_max_train_epochs = int(defaults.get("max_train_epochs", 16))
        self._default_num_repeats = int(defaults.get("num_repeats", 10))

    @property
    def name(self) -> str:
        return "kohya-ss"

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _collect_images(self, images_dir: str) -> list[str]:
        """收集目录中的图片文件路径，最多 MAX_IMAGES 张"""
        img_dir = Path(images_dir)
        if not img_dir.exists():
            return []
        paths = []
        for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
            paths.extend(str(p) for p in img_dir.glob(ext))
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
    # REST API 调用
    # ────────────────────────────────────────────────

    def _api_post_train(self, img_paths: list[str], trigger_word: str,
                        lora_name: str, steps: int, learning_rate: str,
                        rank: int, resolution: int) -> str:
        """POST /train — 启动训练

        Returns:
            task_id
        """
        import httpx

        url = f"{self._api_url.rstrip('/')}/train"

        # 构建 multipart 请求
        files = []
        for p in img_paths:
            files.append(("images", (Path(p).name, open(p, "rb"), "image/png")))

        data = {
            "trigger_word": trigger_word,
            "lora_name": lora_name,
            "steps": str(steps),
            "learning_rate": learning_rate,
            "network_dim": str(rank),
            "resolution": str(resolution),
            "max_train_epochs": str(self._default_max_train_epochs),
            "num_repeats": str(self._default_num_repeats),
        }

        try:
            resp = httpx.post(url, files=files, data=data,
                              headers=self._headers(),
                              timeout=60)
            resp.raise_for_status()
            result = resp.json()
            task_id = result.get("task_id") or result.get("id") or ""
            if not task_id:
                raise RuntimeError(f"API 未返回 task_id: {result}")
            return task_id
        except httpx.ConnectError:
            raise ConnectionError(f"连接被拒绝: {url}")
        except httpx.TimeoutException:
            raise TimeoutError(f"连接超时: {url}")

    def _api_get_status(self, task_id: str) -> dict:
        """GET /status/{task_id} — 查询训练状态

        Returns:
            {"status": "running"|"done"|"error", "progress": 0-100,
             "message": "...", "result_url": "..."}
        """
        import httpx

        url = f"{self._api_url.rstrip('/')}/status/{task_id}"
        resp = httpx.get(url, headers=self._headers(), timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _api_download_result(self, result_url: str, output_path: str) -> str:
        """下载训练结果（.safetensors）"""
        import httpx

        if result_url.startswith("/"):
            result_url = f"{self._api_url.rstrip('/')}{result_url}"

        resp = httpx.get(result_url, headers=self._headers(),
                         timeout=300, follow_redirects=True)
        resp.raise_for_status()

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(resp.content)

        return output_path

    # ────────────────────────────────────────────────
    # 主入口
    # ────────────────────────────────────────────────

    def train_lora(self, char_id: str, images_dir: str, *,
                   trigger_word: str = "",
                   steps: int = 1000,
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

        # 1. 启动训练
        task_id = self._api_post_train(
            img_paths, trigger_word, output_name,
            steps, lr_str, rank, res_val,
        )
        logger.info(f"  训练任务已提交: {task_id}")

        # 2. 轮询等待完成
        start_time = time.time()
        while True:
            if time.time() - start_time > self._timeout:
                raise TimeoutError(f"训练超时（{self._timeout}s）: {task_id}")

            status = self._api_get_status(task_id)
            state = status.get("status", "unknown")
            progress = status.get("progress", 0)
            message = status.get("message", "")

            if state == "done":
                logger.info(f"  训练完成: {message}")
                break
            elif state == "error":
                raise RuntimeError(f"训练失败: {message}")
            else:
                logger.info(f"  训练中... {progress}% {message}")

            time.sleep(self._poll_interval)

        # 3. 下载结果
        output_dir = Path(self._project_dir) / "assets" / "loras"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(output_dir / f"{output_name}.safetensors")

        result_url = status.get("result_url", "")
        if result_url:
            self._api_download_result(result_url, output_path)
        else:
            # 尝试从默认输出目录复制
            lora_path = self._find_output(output_name)
            if lora_path:
                import shutil
                shutil.copy2(lora_path, output_path)
            else:
                raise RuntimeError(
                    f"训练完成但无法获取 .safetensors 文件。\n"
                    f"请手动将训练产物复制到: {output_path}\n"
                    f"文件名必须为: {output_name}.safetensors")

        logger.info(f"LoRA 已保存: {output_path}")
        return output_path

    def _find_output(self, lora_name: str) -> str | None:
        """在常见输出目录中查找 .safetensors 文件"""
        candidates = [
            Path(f"/workspace/kohya_ss/output/{lora_name}.safetensors"),
            Path(f"/workspace/kohya_ss/output/{lora_name}"),
            Path.home() / "kohya_ss" / "output" / f"{lora_name}.safetensors",
            Path.home() / "sd-scripts" / "output" / f"{lora_name}.safetensors",
        ]
        for p in candidates:
            if p.exists() and p.suffix == ".safetensors":
                return str(p)
            if p.is_dir():
                for f in p.glob("**/*.safetensors"):
                    return str(f)
        return None

    # ────────────────────────────────────────────────
    # 状态查询
    # ────────────────────────────────────────────────

    def check_status(self) -> dict:
        """检查 kohya-ss 服务状态"""
        import httpx
        try:
            url = f"{self._api_url.rstrip('/')}/health"
            resp = httpx.get(url, headers=self._headers(), timeout=5)
            return {
                "status": "connected",
                "url": self._api_url,
                "message": f"HTTP {resp.status_code}",
            }
        except httpx.ConnectError:
            return {"status": "disconnected", "url": self._api_url,
                    "error": f"连接被拒绝"}
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
    name="kohya-ss",
    service_type="training",
    factory=lambda cfg: KohyaSSTrainer(cfg),
    description="kohya-ss sd-scripts 远程 LoRA 训练（REST API）",
    priority=10,
    tags=["lora", "training", "kohya", "flux", "sd"],
))

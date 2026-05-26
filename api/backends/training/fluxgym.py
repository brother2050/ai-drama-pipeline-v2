"""FluxGym 训练后端 — 通过 gradio_client 远程调用 FluxGym 训练 LoRA

FluxGym 是 Gradio UI，没有 REST API，通过 gradio_client 远程调用。
架构: 本地管线 → 提交训练任务 → 轮询完成 → 下载 .safetensors
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from api.registry import BackendMeta, registry

logger = logging.getLogger(__name__)

__all__ = ["FluxGymTrainer"]


class FluxGymTrainer:
    """FluxGym 远程 LoRA 训练后端"""

    def __init__(self, config: dict):
        self._api_url = config.get("api_url", "http://127.0.0.1:7860")
        self._timeout = config.get("timeout", 3600)
        self._poll_interval = config.get("poll_interval", 10)
        self._project_dir = config.get("project_dir", "")
        self._client = None

    @property
    def name(self) -> str:
        return "fluxgym"

    def _get_client(self):
        """懒加载 gradio_client"""
        if self._client is None:
            try:
                from gradio_client import Client
                self._client = Client(self._api_url)
            except ImportError:
                raise ImportError("需要安装 gradio_client: pip install gradio_client")
            except Exception as e:
                raise ConnectionError(f"连接 FluxGym 失败 ({self._api_url}): {e}")
        return self._client

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
            trigger_word: 触发词（如 ohwx person）
            steps: 训练步数
            learning_rate: 学习率
            rank: LoRA rank
            resolution: 训练分辨率
            output_name: 输出文件名（默认 {char_id}_lora）

        Returns:
            下载后的本地 .safetensors 路径
        """
        if not output_name:
            output_name = f"{char_id}_lora"

        # 收集训练图片
        img_paths = self._collect_images(images_dir)
        if not img_paths:
            raise FileNotFoundError(f"训练图片目录为空: {images_dir}")

        logger.info(f"开始训练 LoRA: {char_id}, 图片 {len(img_paths)} 张, steps={steps}")

        client = self._get_client()

        # 调用 FluxGym 训练接口
        # FluxGym 典型接口: predict(images, trigger_word, steps, lr, rank, ...)
        # 具体参数需根据 FluxGym 版本调整
        try:
            result = client.predict(
                img_paths,           # 训练图片
                trigger_word or f"ohwx {char_id}",  # 触发词
                steps,               # 步数
                learning_rate,       # 学习率
                rank,                # rank
                resolution,          # 分辨率
                output_name,         # 输出名
                api_name="/train",   # FluxGym 的训练 API 端点
            )
        except Exception as e:
            # 尝试备用端点
            logger.warning(f"/train 端点失败，尝试 /run_training: {e}")
            try:
                result = client.predict(
                    img_paths,
                    trigger_word or f"ohwx {char_id}",
                    steps,
                    learning_rate,
                    rank,
                    resolution,
                    output_name,
                    api_name="/run_training",
                )
            except Exception as e2:
                raise RuntimeError(f"FluxGym 训练失败: {e2}")

        # result 通常是输出文件路径
        lora_path = self._download_result(result, char_id)
        logger.info(f"LoRA 训练完成: {lora_path}")
        return lora_path

    def train_style_lora(self, genre: str, images_dir: str, *,
                         trigger_word: str = "",
                         steps: int = 1000,
                         rank: int = 16,
                         output_name: str = "") -> str:
        """训练风格 LoRA

        Args:
            genre: 风格类型（如 urban, fantasy）
            images_dir: 风格参考图目录
            trigger_word: 触发词
            steps: 训练步数
            rank: LoRA rank
            output_name: 输出文件名

        Returns:
            下载后的本地 .safetensors 路径
        """
        if not output_name:
            output_name = f"style_{genre}_lora"

        img_paths = self._collect_images(images_dir)
        if not img_paths:
            raise FileNotFoundError(f"风格图片目录为空: {images_dir}")

        logger.info(f"开始训练风格 LoRA: {genre}, 图片 {len(img_paths)} 张")

        client = self._get_client()
        try:
            result = client.predict(
                img_paths,
                trigger_word or f"{genre} style",
                steps,
                1e-4,
                rank,
                "512x768",
                output_name,
                api_name="/train",
            )
        except Exception as e:
            raise RuntimeError(f"FluxGym 风格训练失败: {e}")

        return self._download_result(result, f"style_{genre}")

    def check_status(self) -> dict:
        """检查 FluxGym 服务状态"""
        try:
            client = self._get_client()
            # 尝试获取服务信息
            return {"status": "connected", "url": self._api_url}
        except Exception as e:
            return {"status": "disconnected", "url": self._api_url, "error": str(e)}

    def _collect_images(self, images_dir: str) -> list[str]:
        """收集目录中的图片文件路径"""
        img_dir = Path(images_dir)
        if not img_dir.exists():
            return []
        paths = []
        for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
            paths.extend(str(p) for p in img_dir.glob(ext))
        return sorted(paths)

    def _download_result(self, result: Any, prefix: str) -> str:
        """下载训练结果到本地 assets 目录

        Args:
            result: FluxGym 返回的结果（路径或 URL）
            prefix: 文件名前缀

        Returns:
            本地 .safetensors 路径
        """
        output_dir = Path(self._project_dir) / "assets" / "loras"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{prefix}.safetensors"

        if isinstance(result, str):
            result_path = Path(result)
            if result_path.exists():
                # 本地文件，直接复制
                import shutil
                shutil.copy2(result_path, output_path)
                return str(output_path)
            elif result.startswith("http"):
                # URL，下载
                import httpx
                resp = httpx.get(result, timeout=120)
                resp.raise_for_status()
                output_path.write_bytes(resp.content)
                return str(output_path)

        # result 可能是 tuple/list，取第一个路径
        if isinstance(result, (list, tuple)):
            for item in result:
                if isinstance(item, str) and item.endswith(".safetensors"):
                    return self._download_result(item, prefix)

        raise RuntimeError(f"无法解析 FluxGym 返回结果: {result}")

    def shutdown(self):
        """关闭连接"""
        self._client = None


# ── 注册到全局注册表 ──────────────────────────────────────

registry.register(BackendMeta(
    name="fluxgym",
    service_type="training",
    factory=lambda cfg: FluxGymTrainer(cfg),
    description="FluxGym 远程 LoRA 训练（Gradio API）",
    priority=10,
    tags=["lora", "training", "flux", "gradio"],
))

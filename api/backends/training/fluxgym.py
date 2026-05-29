"""FluxGym 训练后端 — 通过 gradio_client 远程调用 FluxGym 训练 LoRA

FluxGym 是 Gradio UI，没有 REST API，通过 gradio_client 远程调用。
架构: 本地管线 → 提交训练任务 → 轮询完成 → 下载 .safetensors
"""

from __future__ import annotations

import logging
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
                raise ImportError(
                    "需要安装 gradio_client: pip install 'ai-drama-pipeline[training]'\n"
                    "或直接: pip install gradio_client"
                )
            except Exception as e:
                raise ConnectionError(f"连接 FluxGym 失败 ({self._api_url}): {e}")
        return self._client

    def _find_train_api(self, client) -> tuple[str, list[dict]] | tuple[None, None]:
        """自动发现训练 API 端点并返回参数信息

        FluxGym 不同版本的 API 端点名不同，自动探测可用端点。
        优先级: 包含 train 关键词的端点 > 第一个可用端点

        Returns:
            (api_name, params_info) 或 (None, None)
        """
        try:
            info = client.view_api(return_format="dict")
            endpoints = info.get("named_endpoints", {})
            # 优先找包含 train 的端点
            train_candidates = [
                name for name in endpoints
                if "train" in name.lower()
            ]
            if train_candidates:
                for preferred in ("/train", "/run_training"):
                    if preferred in train_candidates:
                        return preferred, endpoints[preferred].get("parameters", [])
                name = train_candidates[0]
                return name, endpoints[name].get("parameters", [])
            # 没有 train 关键词，返回第一个端点
            if endpoints:
                name = next(iter(endpoints))
                return name, endpoints[name].get("parameters", [])
        except Exception as e:
            logger.debug(f"API 端点发现失败: {e}")
        return None, None

    def _build_predict_args(self, params_info: list[dict],
                            img_paths: list[str], trigger_word: str,
                            steps: int, learning_rate: float,
                            rank: int, resolution: str,
                            output_name: str) -> list:
        """根据端点参数元数据构建 predict() 参数列表

        不同版本 FluxGym 的参数顺序和数量不同，这里根据参数名智能映射。
        """
        if not params_info:
            # 无参数信息，使用默认位置参数
            return [img_paths, trigger_word, steps, learning_rate,
                    rank, resolution, output_name]

        args = []
        for param in params_info:
            pname = (param.get("parameter_name") or param.get("name") or "").lower()
            ptype = param.get("type", "")

            # 按参数名映射
            if "image" in pname or "photo" in pname or "file" in pname:
                args.append(img_paths)
            elif "trigger" in pname or "token" in pname or "keyword" in pname:
                args.append(trigger_word)
            elif "step" in pname:
                args.append(steps)
            elif "lr" in pname or "learning" in pname or "rate" in pname:
                args.append(learning_rate)
            elif "rank" in pname or "dim" in pname:
                args.append(rank)
            elif "resol" in pname or "size" in pname:
                args.append(resolution)
            elif "output" in pname or "name" in pname or "save" in pname:
                args.append(output_name)
            else:
                # 未知参数，跳过（gradio_client 有默认值）
                continue

        # 确保至少有基本参数
        if len(args) < 2:
            return [img_paths, trigger_word, steps, learning_rate,
                    rank, resolution, output_name]

        return args

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

        # 自动发现训练 API 端点
        api_name, params_info = self._find_train_api(client)
        if not api_name:
            raise RuntimeError(
                f"FluxGym ({self._api_url}) 未发现可用的训练 API 端点。\n"
                "请确认 FluxGym 服务已启动且版本受支持。"
            )
        logger.info(f"使用 FluxGym 端点: {api_name}，参数: {len(params_info)} 个")

        # 根据端点元数据构建参数
        args = self._build_predict_args(
            params_info, img_paths,
            trigger_word or f"ohwx {char_id}",
            steps, learning_rate, rank, resolution, output_name,
        )

        # 调用 FluxGym 训练接口
        try:
            result = client.predict(*args, api_name=api_name)
        except Exception as e:
            raise RuntimeError(
                f"FluxGym 训练失败 ({api_name}): {e}\n"
                f"端点参数: {[p.get('parameter_name') or p.get('name') for p in params_info]}\n"
                f"传入参数数: {len(args)}"
            )

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
        api_name, params_info = self._find_train_api(client)
        if not api_name:
            raise RuntimeError(f"FluxGym ({self._api_url}) 未发现可用的训练 API 端点")
        args = self._build_predict_args(
            params_info, img_paths,
            trigger_word or f"{genre} style",
            steps, 1e-4, rank, "512x768", output_name,
        )
        try:
            result = client.predict(*args, api_name=api_name)
        except Exception as e:
            raise RuntimeError(f"FluxGym 风格训练失败 ({api_name}): {e}")

        return self._download_result(result, f"style_{genre}")

    def check_status(self) -> dict:
        """检查 FluxGym 服务状态"""
        try:
            client = self._get_client()
            api_name, params = self._find_train_api(client)
            return {
                "status": "connected",
                "url": self._api_url,
                "train_endpoint": api_name,
                "param_count": len(params) if params else 0,
                "param_names": [p.get("parameter_name") or p.get("name") for p in (params or [])],
            }
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

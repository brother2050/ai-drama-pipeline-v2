"""GPU 适配器 — 根据显存自动调整生成参数"""
from __future__ import annotations
import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)

# GPU → 推荐配置
GPU_PRESETS = {
    # (min_vram_mb, max_vram_mb): {overrides}
    (0, 0): {"image_backend": "sd15", "video_backend": "animatediff", "resolution": [320, 180],
             "image_steps": 8, "video_frames": 4, "note": "无 GPU / API 模式"},
    (8000, 16000): {"image_backend": "sd15", "video_backend": "animatediff",
                    "resolution": [512, 512], "image_steps": 20, "video_frames": 8},
    (16000, 24000): {"image_backend": "sd15", "video_backend": "animatediff",
                     "resolution": [768, 432], "image_steps": 20, "video_frames": 12},
    (24000, 40000): {"image_backend": "flux", "video_backend": "animatediff",
                     "resolution": [1024, 576], "image_steps": 28, "video_frames": 16},
    (40000, 999999): {"image_backend": "flux", "video_backend": "cogvideox",
                      "resolution": [1280, 720], "image_steps": 28, "video_frames": 16},
}


def detect_vram() -> int:
    """检测 GPU 显存（MB），无 GPU 返回 0"""
    if not shutil.which("nvidia-smi"):
        return 0
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return int(r.stdout.strip().split("\n")[0])
    except Exception:
        pass
    return 0


def get_gpu_config(vram_mb: int | None = None) -> dict:
    """根据显存返回推荐配置"""
    if vram_mb is None:
        vram_mb = detect_vram()

    for (min_v, max_v), cfg in GPU_PRESETS.items():
        if min_v <= vram_mb < max_v:
            return {**cfg, "vram_mb": vram_mb}

    return {"vram_mb": vram_mb, "note": "未知 GPU，使用默认配置"}


def auto_adjust(config: dict, vram_mb: int | None = None) -> dict:
    """根据 GPU 自动调整配置"""
    gpu_cfg = get_gpu_config(vram_mb)
    if gpu_cfg.get("vram_mb", 0) == 0:
        logger.info("无本地 GPU，使用 API 模式")
        return config

    models = config.setdefault("models", {})
    for key in ("image_backend", "video_backend"):
        if key in gpu_cfg:
            models[key] = gpu_cfg[key]
            logger.info(f"GPU 适配: {key} → {gpu_cfg[key]}")

    if "resolution" in gpu_cfg:
        config.setdefault("project", {})["resolution"] = gpu_cfg["resolution"]

    logger.info(f"GPU 适配: {gpu_cfg}")
    return config

"""GPU 检测 — 跨平台"""

from __future__ import annotations
import shutil
import subprocess
import logging

logger = logging.getLogger(__name__)

def detect_gpu() -> dict:
    """检测 GPU 信息，返回 {name, vram_mb, cuda, available}"""
    info = {"name": "N/A", "vram_mb": 0, "cuda": "N/A", "available": False}
    if not shutil.which("nvidia-smi"):
        return info
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            parts = [p.strip() for p in r.stdout.strip().split(",")]
            if len(parts) >= 3:
                info = {"name": parts[0], "vram_mb": int(parts[1]),
                        "cuda": parts[2], "available": True}
    except Exception as e:
        logger.debug(f"GPU detect failed: {e}")
    return info

"""GPU 检测 — 已禁用本地检测

项目本身不使用 GPU，GPU 由三方工具（ComfyUI 等）管理，
本地检测 nvidia-smi 无意义。
"""

from __future__ import annotations


def detect_gpu() -> dict:
    """返回固定占位，不执行本地 GPU 检测"""
    return {"name": "N/A", "vram_mb": 0, "cuda": "N/A", "available": False}

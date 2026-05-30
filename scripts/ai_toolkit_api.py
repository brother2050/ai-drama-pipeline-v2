#!/usr/bin/env python3
"""AI Toolkit 轻量 REST API 包装 — 部署在 GPU 服务器上

在 AI Toolkit 所在机器上启动:
    pip install fastapi uvicorn
    python scripts/ai_toolkit_api.py --port 7860 --ai-toolkit-path /path/to/ai-toolkit

API:
    POST /train         — 启动训练（multipart: images + form params）
    GET  /status/{id}   — 查询训练状态
    GET  /health        — 健康检查
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("ai_toolkit_api")

app = FastAPI(title="AI Toolkit Training API")

# ── 全局状态 ──
_tasks: dict[str, dict] = {}
_lock = threading.Lock()
_AI_TOOLKIT_PATH = ""
_OUTPUT_DIR = Path("/tmp/ai_toolkit_output")


def _update_task(task_id: str, **kwargs):
    with _lock:
        if task_id in _tasks:
            _tasks[task_id].update(kwargs)


@app.get("/health")
def health():
    return {"status": "ok", "ai_toolkit_path": _AI_TOOLKIT_PATH}


@app.post("/train")
async def train(
    images: list[UploadFile] = File(..., description="训练图片"),
    trigger_word: str = Form("ohwx person"),
    lora_name: str = Form("my_lora"),
    steps: int = Form(600),
    learning_rate: str = Form("1e-4"),
    network_dim: int = Form(16),
    resolution: str = Form("512"),
    max_train_epochs: int = Form(16),
    num_repeats: int = Form(10),
    base_model: str = Form("ostris/Flex.1-alpha"),
):
    task_id = str(uuid.uuid4())[:8]
    task_dir = _OUTPUT_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    # 保存图片
    img_dir = task_dir / "images"
    img_dir.mkdir(exist_ok=True)
    for img in images:
        dst = img_dir / img.filename
        with open(dst, "wb") as f:
            shutil.copyfileobj(img.file, f)

    # 生成 caption 文件（每张图一个 .txt）
    for img_file in img_dir.iterdir():
        if img_file.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            cap_file = img_file.with_suffix(".txt")
            if not cap_file.exists():
                cap_file.write_text(trigger_word, encoding="utf-8")

    # 解析分辨率
    try:
        res_list = [int(r.strip()) for r in resolution.split(",")]
    except ValueError:
        res_list = [512]
    if len(res_list) == 1:
        res_list = res_list * 3  # [512, 512, 512]

    # 生成 AI Toolkit 配置
    config = {
        "job": "extension",
        "config": {
            "name": lora_name,
            "process": [{
                "type": "sd_trainer",
                "training_folder": str(task_dir / "output"),
                "device": "cuda:0",
                "trigger_word": trigger_word,
                "network": {
                    "type": "lora",
                    "linear": network_dim,
                    "linear_alpha": network_dim,
                },
                "save": {
                    "dtype": "float16",
                    "save_every": max(1, steps // 4),
                    "max_step_saves_to_keep": 2,
                },
                "datasets": [{
                    "folder_path": str(img_dir),
                    "caption_ext": "txt",
                    "caption_dropout_rate": 0.05,
                    "shuffle_tokens": False,
                    "cache_latents_to_disk": True,
                    "resolution": res_list,
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
                    "lr": float(learning_rate),
                    "ema_config": {"use_ema": True, "ema_decay": 0.99},
                    "dtype": "bf16",
                },
                "model": {
                    "name_or_path": base_model,
                    "is_flux": True,
                    "quantize": True,
                },
                "sample": {
                    "sampler": "flowmatch",
                    "sample_every": steps,  # 只在最后采样一次
                    "width": res_list[0],
                    "height": res_list[0],
                    "prompts": [f"{trigger_word} portrait"],
                },
            }],
        },
    }

    config_path = task_dir / "config.yaml"
    import yaml
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    _tasks[task_id] = {
        "status": "running",
        "progress": 0,
        "message": "训练启动中...",
        "lora_name": lora_name,
        "start_time": time.time(),
    }

    # 后台启动训练
    thread = threading.Thread(target=_run_training, args=(task_id, config_path, task_dir))
    thread.daemon = True
    thread.start()

    return {"task_id": task_id, "status": "submitted"}


def _run_training(task_id: str, config_path: Path, task_dir: Path):
    """后台执行 AI Toolkit 训练"""
    global _AI_TOOLKIT_PATH
    run_py = Path(_AI_TOOLKIT_PATH) / "run.py"
    if not run_py.exists():
        _update_task(task_id, status="error", message=f"run.py 不存在: {run_py}")
        return

    try:
        cmd = ["python", str(run_py), str(config_path)]
        logger.info(f"[{task_id}] 启动训练: {' '.join(cmd)}")

        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )

        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            logger.info(f"[{task_id}] {line}")

            # 解析进度（AI Toolkit 输出 step/total 格式）
            if "step" in line.lower() and "/" in line:
                try:
                    parts = line.split()
                    for p in parts:
                        if "/" in p and p.replace("/", "").isdigit():
                            nums = p.split("/")
                            current, total = int(nums[0]), int(nums[1])
                            pct = int(current / total * 100)
                            _update_task(task_id, progress=pct,
                                         message=f"Step {current}/{total}")
                            break
                except (ValueError, IndexError):
                    pass

        proc.wait()

        if proc.returncode == 0:
            # 查找输出的 .safetensors 文件
            output_dir = task_dir / "output"
            lora_files = list(output_dir.rglob("*.safetensors"))
            if lora_files:
                _update_task(
                    task_id, status="done", progress=100,
                    message="训练完成",
                    result_path=str(lora_files[-1]),
                )
            else:
                _update_task(
                    task_id, status="error",
                    message="训练完成但未找到 .safetensors 文件",
                )
        else:
            _update_task(
                task_id, status="error",
                message=f"训练退出码: {proc.returncode}",
            )

    except Exception as e:
        logger.error(f"[{task_id}] 训练异常: {e}")
        _update_task(task_id, status="error", message=str(e))


@app.get("/status/{task_id}")
def get_status(task_id: str):
    with _lock:
        task = _tasks.get(task_id)
    if not task:
        return JSONResponse(status_code=404, content={"error": "任务不存在"})
    return task


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Toolkit REST API")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--ai-toolkit-path", required=True, help="AI Toolkit 安装路径")
    parser.add_argument("--output-dir", default="/tmp/ai_toolkit_output")
    args = parser.parse_args()

    _AI_TOOLKIT_PATH = args.ai_toolkit_path
    _OUTPUT_DIR = Path(args.output_dir)
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=args.port)

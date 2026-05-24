"""Celery 应用配置 — 异步任务队列核心"""
from __future__ import annotations

import logging
import os
import traceback

from celery import Celery

logger = logging.getLogger(__name__)

broker = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
backend = os.environ.get("REDIS_BACKEND_URL", broker.replace("/0", "/1"))

app = Celery("drama", broker=broker, backend=backend)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=3600,
    task_time_limit=3900,
    result_expires=86400,
    task_default_queue="drama",
    task_routes={
        "pipeline.tts": {"queue": "drama"},
        "pipeline.first_frame": {"queue": "drama"},
        "pipeline.video": {"queue": "drama"},
        "pipeline.lipsync": {"queue": "drama"},
        "pipeline.shot": {"queue": "drama"},
        "pipeline.preview": {"queue": "drama"},
        "pipeline.produce": {"queue": "drama"},
        "pipeline.post": {"queue": "drama"},
        "pipeline.portraits": {"queue": "drama"},
    },
)


def format_task_error(exc: Exception, task_name: str = "", task_id: str = "") -> dict:
    """统一的 Celery 任务错误格式

    Returns:
        {"status": "error", "error": str, "error_type": str, "task": str, "task_id": str}
    """
    return {
        "status": "error",
        "error": str(exc),
        "error_type": type(exc).__name__,
        "task": task_name,
        "task_id": task_id,
        "traceback": traceback.format_exc(),
    }


# 统一的失败回调
@app.task(bind=True)
def _on_failure(self, exc, task_id, args, kwargs, einfo):
    logger.error(f"任务 {task_id} 失败: {exc} ({type(exc).__name__})")

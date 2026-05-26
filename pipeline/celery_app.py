"""Celery 应用配置 — 异步任务队列核心"""
from __future__ import annotations

import logging
import os
import traceback

from celery import Celery
from celery.signals import task_failure

logger = logging.getLogger(__name__)

broker = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
backend = os.environ.get("REDIS_BACKEND_URL", broker.replace("/0", "/1"))

app = Celery("drama", broker=broker, backend=backend,
             include=["pipeline.tasks"])

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=3600,
    task_time_limit=3900,
    result_expires=86400,
    task_default_queue="drama",
    task_routes={
        "pipeline.step.tts": {"queue": "drama"},
        "pipeline.step.first_frame": {"queue": "drama"},
        "pipeline.step.video": {"queue": "drama"},
        "pipeline.step.lipsync": {"queue": "drama"},
        "pipeline.shot": {"queue": "drama"},
        "pipeline.preview": {"queue": "drama"},
        "pipeline.produce": {"queue": "drama"},
        "pipeline.post": {"queue": "drama"},
        "pipeline.portraits": {"queue": "drama"},
        "pipeline.scene_images": {"queue": "drama"},
        "pipeline.tts_single": {"queue": "drama"},
        "pipeline.music": {"queue": "drama"},
        "pipeline.subtitle": {"queue": "drama"},
        "pipeline.ai.storyboard": {"queue": "drama"},
        "pipeline.ai.characters": {"queue": "drama"},
        "pipeline.ai.scenes": {"queue": "drama"},
        "pipeline.seko.import": {"queue": "drama"},
        "ai_chat_edit": {"queue": "drama"},
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


# 全局失败回调 — 所有任务失败时自动记录日志
@task_failure.connect
def _on_task_failure(sender, task_id, exception, traceback, einfo, **kwargs):
    logger.error(f"任务失败: {task_id} ({sender.name}): {exception} ({type(exception).__name__})")

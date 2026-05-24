"""Celery 应用配置 — 异步任务队列核心"""
from __future__ import annotations

import os

from celery import Celery

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
    task_acks_late=True,             # 任务完成后才确认，防止 worker 崩溃丢任务
    worker_prefetch_multiplier=1,    # 每次只取 1 个任务，适配长耗时 AI 任务
    task_soft_time_limit=3600,       # 软超时 1 小时
    task_time_limit=3900,            # 硬超时 65 分钟
    result_expires=86400,            # 结果保留 24 小时
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

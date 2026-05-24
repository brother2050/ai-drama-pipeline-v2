"""Celery 应用配置"""
from __future__ import annotations
import os

try:
    from celery import Celery
    broker = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    app = Celery("drama", broker=broker, backend=broker.replace("/0", "/1"))
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="Asia/Shanghai",
        enable_utc=True,
        task_track_started=True,
    )
except ImportError:
    app = None

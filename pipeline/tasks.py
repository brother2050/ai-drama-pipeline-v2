"""管线异步任务"""
from __future__ import annotations
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# 尝试导入 Celery
try:
    from pipeline.celery_app import app as celery_app
    HAS_CELERY = celery_app is not None
except ImportError:
    HAS_CELERY = False


def _ensure_path():
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


if HAS_CELERY:
    @celery_app.task(bind=True, name="pipeline.preview")
    def preview_task(self, config_path: str, episode: int, preset: str = "draft"):
        _ensure_path()
        from pipeline.preview import run_preview
        run_preview(config_path, episode, preset)
        return {"status": "done", "episode": episode, "preset": preset}

    @celery_app.task(bind=True, name="pipeline.produce")
    def produce_task(self, config_path: str, episode: int):
        _ensure_path()
        from pipeline.producer import run_produce
        run_produce(config_path, episode)
        return {"status": "done", "episode": episode}

    @celery_app.task(bind=True, name="pipeline.post")
    def post_task(self, config_path: str, episode: int, vertical: bool = False):
        _ensure_path()
        from post.production import run_post
        run_post(config_path, episode, vertical)
        return {"status": "done", "episode": episode}

    @celery_app.task(bind=True, name="pipeline.shot_step")
    def shot_step_task(self, config_path: str, episode: int, shot_id: str, step: str, preset: str = ""):
        _ensure_path()
        from infra.config import Config
        from flow.orchestrator import ShotOrchestrator
        cfg = Config(config_path)
        orch = ShotOrchestrator(cfg.data)
        # TODO: 从数据库加载 shot 数据
        return {"status": "done", "shot_id": shot_id, "step": step}

"""FastAPI 应用工厂"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """创建 FastAPI 应用"""

    # 配置日志（含文件输出）
    from web.services import setup_logging
    log_dir = Path(__file__).resolve().parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    setup_logging(level="INFO", log_file=str(log_dir / "app.log"))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("🎬 AI 短剧工作台 v2 已启动")
        yield
        logger.info("🎬 工作台已关闭")

    app = FastAPI(title="AI 短剧工作台 v2", version="2.0", lifespan=lifespan)

    # CORS
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    # 注册路由
    from web.routers import api
    app.include_router(api.router, prefix="/api")

    # 静态文件
    from fastapi.staticfiles import StaticFiles
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app

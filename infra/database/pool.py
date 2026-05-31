"""数据库连接池 — PostgreSQL（必须）"""
from __future__ import annotations
import logging
import os
import threading
from contextlib import contextmanager

logger = logging.getLogger(__name__)

_pool = None
_pool_lock = threading.Lock()


class PgPool:
    """PostgreSQL 连接池"""

    def __init__(self, dsn: str):
        from psycopg2 import pool as pg_pool
        self._pool = pg_pool.ThreadedConnectionPool(1, 20, dsn)
        # 初始化 schema
        from infra.database.schema import init_schema
        conn = self._pool.getconn()
        try:
            init_schema(conn)
        finally:
            self._pool.putconn(conn)

    def connect(self):
        conn = self._pool.getconn()
        # 快速检查：conn.closed 是属性，无网络开销
        if getattr(conn, 'closed', False):
            try:
                self._pool.putconn(conn, close=True)
            except Exception:
                logger.debug(f"{type(e).__name__}: {e}")
            conn = self._pool.getconn()
        # 活性检查：连接可能被服务端关闭（idle timeout），验证是否可用
        try:
            conn.poll()
        except Exception:
            # 连接已断开，丢弃并获取新连接
            try:
                self._pool.putconn(conn, close=True)
            except Exception:
                logger.debug(f"{type(e).__name__}: {e}")
            conn = self._pool.getconn()
        return conn

    def release(self, conn):
        self._pool.putconn(conn)

    @contextmanager
    def connection(self):
        """安全连接上下文管理器 — 异常时自动 rollback，防止连接处于错误状态"""
        conn = self.connect()
        try:
            yield conn
        except Exception:
            try:
                conn.rollback()
            except Exception:
                logger.debug(f"{type(e).__name__}: {e}")
            raise
        finally:
            self.release(conn)

    def close(self):
        self._pool.closeall()


def get_pool() -> PgPool:
    """获取 PostgreSQL 连接池（必须配置 AI_DRAMA_DB_DSN）"""
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is not None:
            return _pool
        dsn = os.environ.get("AI_DRAMA_DB_DSN", "")
        if not dsn:
            raise RuntimeError(
                "AI_DRAMA_DB_DSN 未配置。PostgreSQL 是必须依赖。\n"
                "示例: AI_DRAMA_DB_DSN=postgresql://drama:drama123@127.0.0.1:5432/ai_drama\n"
                "请先创建数据库: CREATE DATABASE ai_drama;"
            )
        _pool = PgPool(dsn)
        logger.info("PostgreSQL 连接池已初始化")
    return _pool


def placeholder() -> str:
    """PostgreSQL 参数占位符"""
    return "%s"

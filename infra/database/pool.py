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
        import psycopg2
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
        # 健康检查：如果连接已关闭或不可用，丢弃并重新获取
        if getattr(conn, 'closed', False):
            try:
                self._pool.putconn(conn, close=True)
            except Exception:
                pass
            conn = self._pool.getconn()
        else:
            cur = None
            try:
                cur = conn.cursor()
                cur.execute("SELECT 1")
            except Exception:
                try:
                    if cur:
                        cur.close()
                except Exception:
                    pass
                try:
                    self._pool.putconn(conn, close=True)
                except Exception:
                    pass
                conn = self._pool.getconn()
            else:
                cur.close()
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
                pass
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

"""数据库连接池 — PostgreSQL / SQLite 双模式"""
from __future__ import annotations
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_pool = None


class SQLitePool:
    """SQLite 连接池（轻量回退）"""
    def __init__(self, path: str):
        self._path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        # 初始化 schema
        from infra.database.schema import init_schema
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        init_schema(conn)
        conn.close()

    def connect(self):
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def release(self, conn):
        """SQLite 连接释放（兼容 PgPool 接口）"""
        conn.close()

    def close(self):
        pass


class PgPool:
    """PostgreSQL 连接池"""
    def __init__(self, dsn: str):
        import psycopg2
        from psycopg2 import pool as pg_pool
        self._pool = pg_pool.ThreadedConnectionPool(1, 10, dsn)
        # 初始化 schema
        from infra.database.schema import init_schema
        conn = self._pool.getconn()
        try:
            init_schema(conn)
        finally:
            self._pool.putconn(conn)

    def connect(self):
        return self._pool.getconn()

    def release(self, conn):
        self._pool.putconn(conn)

    def close(self):
        self._pool.closeall()


def get_pool():
    global _pool
    if _pool is None:
        dsn = os.environ.get("AI_DRAMA_DB_DSN", "")
        if dsn:
            try:
                _pool = PgPool(dsn)
                logger.info("使用 PostgreSQL")
            except Exception as e:
                logger.warning(f"PostgreSQL 连接失败: {e}，回退 SQLite")
                _pool = SQLitePool("data/drama.db")
        else:
            _pool = SQLitePool("data/drama.db")
            logger.info("使用 SQLite")
    return _pool


def is_postgres(pool) -> bool:
    """判断当前 pool 是否为 PostgreSQL"""
    return isinstance(pool, PgPool)


def placeholder(pool) -> str:
    """返回当前数据库的参数占位符"""
    return "%s" if is_postgres(pool) else "?"

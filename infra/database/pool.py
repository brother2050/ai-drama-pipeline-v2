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

    def connect(self):
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def close(self):
        pass


class PgPool:
    """PostgreSQL 连接池"""
    def __init__(self, dsn: str):
        import psycopg2
        from psycopg2 import pool as pg_pool
        self._pool = pg_pool.ThreadedConnectionPool(1, 10, dsn)

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

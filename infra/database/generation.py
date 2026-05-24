"""生成状态数据库操作"""
from __future__ import annotations
import json
import time
from typing import Any

from infra.database.pool import is_postgres


def _ph(pool) -> str:
    return "%s" if is_postgres(pool) else "?"


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    if hasattr(row, 'keys'):
        return {k: row[k] for k in row.keys()}
    return {}


def upsert_status(pool, episode: int, shot_id: str, stage: str,
                  status: str = "pending", path: str = "", error: str = "",
                  elapsed: float = 0.0):
    """写入/更新生成状态"""
    conn = pool.connect()
    try:
        cur = conn.cursor()
        ph = _ph(pool)
        if is_postgres(pool):
            cur.execute(f"""
                INSERT INTO generation_status (episode, shot_id, stage, status, path, error, elapsed, updated_at)
                VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, CURRENT_TIMESTAMP)
                ON CONFLICT (episode, shot_id, stage) DO UPDATE SET
                    status=EXCLUDED.status, path=EXCLUDED.path, error=EXCLUDED.error,
                    elapsed=EXCLUDED.elapsed, updated_at=CURRENT_TIMESTAMP
            """, (episode, shot_id, stage, status, path, error, elapsed))
        else:
            cur.execute(f"""
                INSERT OR REPLACE INTO generation_status (episode, shot_id, stage, status, path, error, elapsed, updated_at)
                VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, CURRENT_TIMESTAMP)
            """, (episode, shot_id, stage, status, path, error, elapsed))
        conn.commit()
    finally:
        pool.release(conn)


def get_shot_status(pool, episode: int, shot_id: str) -> list[dict]:
    """获取镜头的所有步骤状态"""
    conn = pool.connect()
    try:
        cur = conn.cursor()
        ph = _ph(pool)
        cur.execute(f"SELECT * FROM generation_status WHERE episode = {ph} AND shot_id = {ph} ORDER BY stage",
                    (episode, shot_id))
        return [_row_to_dict(r) for r in cur.fetchall()]
    finally:
        pool.release(conn)


def get_episode_statuses(pool, episode: int) -> list[dict]:
    """获取整集所有镜头的生成状态"""
    conn = pool.connect()
    try:
        cur = conn.cursor()
        ph = _ph(pool)
        cur.execute(f"SELECT * FROM generation_status WHERE episode = {ph} ORDER BY shot_id, stage",
                    (episode,))
        return [_row_to_dict(r) for r in cur.fetchall()]
    finally:
        pool.release(conn)


def get_pending_shots(pool, episode: int, stage: str) -> list[str]:
    """获取指定阶段未完成的镜头 ID"""
    conn = pool.connect()
    try:
        cur = conn.cursor()
        ph = _ph(pool)
        cur.execute(f"""SELECT DISTINCT shot_id FROM generation_status
                        WHERE episode = {ph} AND stage = {ph} AND status != 'done'""",
                    (episode, stage))
        return [r['shot_id'] if hasattr(r, 'keys') else r[0] for r in cur.fetchall()]
    finally:
        pool.release(conn)


def clear_episode(pool, episode: int):
    """清除集的生成状态（重新生成前调用）"""
    conn = pool.connect()
    try:
        cur = conn.cursor()
        ph = _ph(pool)
        cur.execute(f"DELETE FROM generation_status WHERE episode = {ph}", (episode,))
        conn.commit()
    finally:
        pool.release(conn)

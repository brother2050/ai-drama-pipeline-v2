"""生成状态数据库操作 — PostgreSQL"""
from __future__ import annotations


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
    with pool.connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO generation_status (episode, shot_id, stage, status, path, error, elapsed, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (episode, shot_id, stage) DO UPDATE SET
                status=EXCLUDED.status, path=EXCLUDED.path, error=EXCLUDED.error,
                elapsed=EXCLUDED.elapsed, updated_at=CURRENT_TIMESTAMP
        """, (episode, shot_id, stage, status, path, error, elapsed))
        conn.commit()


def get_shot_status(pool, episode: int, shot_id: str) -> list[dict]:
    """获取镜头的所有步骤状态"""
    with pool.connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM generation_status WHERE episode = %s AND shot_id = %s ORDER BY stage",
                    (episode, shot_id))
        return [_row_to_dict(r) for r in cur.fetchall()]


def get_episode_statuses(pool, episode: int) -> list[dict]:
    """获取整集所有镜头的生成状态"""
    with pool.connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM generation_status WHERE episode = %s ORDER BY shot_id, stage",
                    (episode,))
        return [_row_to_dict(r) for r in cur.fetchall()]


def get_pending_shots(pool, episode: int, stage: str) -> list[str]:
    """获取指定阶段未完成的镜头 ID"""
    with pool.connection() as conn:
        cur = conn.cursor()
        cur.execute("""SELECT DISTINCT shot_id FROM generation_status
                        WHERE episode = %s AND stage = %s AND status != 'done'""",
                    (episode, stage))
        return [r['shot_id'] if hasattr(r, 'keys') else r[0] for r in cur.fetchall()]


def clear_episode(pool, episode: int):
    """清除集的生成状态（重新生成前调用）"""
    with pool.connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM generation_status WHERE episode = %s", (episode,))
        conn.commit()

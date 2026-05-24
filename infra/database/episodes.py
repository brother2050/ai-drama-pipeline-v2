"""集数据库操作"""
from __future__ import annotations

from infra.database.pool import is_postgres


def _ph(pool) -> str:
    return "%s" if is_postgres(pool) else "?"


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    if hasattr(row, 'keys'):
        return {k: row[k] for k in row.keys()}
    return {}


def get_all(pool) -> list[dict]:
    conn = pool.connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM episodes ORDER BY episode")
        return [_row_to_dict(r) for r in cur.fetchall()]
    finally:
        pool.release(conn)


def upsert(pool, episode: int, data: dict):
    conn = pool.connect()
    try:
        cur = conn.cursor()
        ph = _ph(pool)
        if is_postgres(pool):
            cur.execute(f"""
                INSERT INTO episodes (episode, title, status, shot_count)
                VALUES ({ph}, {ph}, {ph}, {ph})
                ON CONFLICT (episode) DO UPDATE SET
                    title=EXCLUDED.title, status=EXCLUDED.status, shot_count=EXCLUDED.shot_count
            """, (episode, data.get("title", ""), data.get("status", "pending"),
                  data.get("shot_count", 0)))
        else:
            cur.execute(f"""
                INSERT OR REPLACE INTO episodes (episode, title, status, shot_count)
                VALUES ({ph}, {ph}, {ph}, {ph})
            """, (episode, data.get("title", ""), data.get("status", "pending"),
                  data.get("shot_count", 0)))
        conn.commit()
    finally:
        pool.release(conn)

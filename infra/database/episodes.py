"""集数据库操作 — PostgreSQL"""
from __future__ import annotations


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    if hasattr(row, 'keys'):
        return {k: row[k] for k in row.keys()}
    return {}


def get_all(pool) -> list[dict]:
    with pool.connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM episodes ORDER BY episode")
        return [_row_to_dict(r) for r in cur.fetchall()]


def upsert(pool, episode: int, data: dict):
    with pool.connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO episodes (episode, title, status, shot_count)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (episode) DO UPDATE SET
                title=EXCLUDED.title, status=EXCLUDED.status, shot_count=EXCLUDED.shot_count
        """, (episode, data.get("title", ""), data.get("status", "pending"),
              data.get("shot_count", 0)))
        conn.commit()

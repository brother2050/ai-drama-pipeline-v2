"""集数据库操作"""
from __future__ import annotations

def get_all(pool) -> list[dict]:
    conn = pool.connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM episodes ORDER BY episode")
        return [dict(r) for r in cur.fetchall()]
    finally:
        _release(pool, conn)

def upsert(pool, episode: int, data: dict):
    conn = pool.connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO episodes (episode, title, status, shot_count)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (episode) DO UPDATE SET
                title=EXCLUDED.title, status=EXCLUDED.status, shot_count=EXCLUDED.shot_count
        """, (episode, data.get("title", ""), data.get("status", "pending"),
              data.get("shot_count", 0)))
        conn.commit()
    finally:
        _release(pool, conn)

def _release(pool, conn):
    if hasattr(pool, 'release'):
        pool.release(conn)
    else:
        conn.close()

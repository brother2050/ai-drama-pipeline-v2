"""镜头数据库操作"""
from __future__ import annotations
from typing import Any

def get_by_episode(pool, episode: int) -> list[dict]:
    conn = pool.connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM shots WHERE episode = %s ORDER BY shot_id", (episode,))
        return [dict(r) for r in cur.fetchall()]
    finally:
        _release(pool, conn)

def upsert(pool, episode: int, shot_id: str, data: dict):
    conn = pool.connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO shots (episode, shot_id, scene_id, characters, action, dialogue,
                              camera, shot_type, duration, emotion, outfit)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (episode, shot_id) DO UPDATE SET
                scene_id=EXCLUDED.scene_id, characters=EXCLUDED.characters,
                action=EXCLUDED.action, dialogue=EXCLUDED.dialogue
        """, (episode, shot_id, data.get("scene", ""), data.get("characters", ""),
              data.get("action", ""), data.get("dialogue", ""),
              data.get("camera", ""), data.get("shot_type", ""),
              data.get("duration", 0), data.get("emotion", ""), data.get("outfit", "")))
        conn.commit()
    finally:
        _release(pool, conn)

def _release(pool, conn):
    if hasattr(pool, 'release'):
        pool.release(conn)
    else:
        conn.close()

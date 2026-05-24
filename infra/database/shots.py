"""镜头数据库操作 — PostgreSQL"""
from __future__ import annotations
from typing import Any


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    if hasattr(row, 'keys'):
        return {k: row[k] for k in row.keys()}
    return {}


def get_by_episode(pool, episode: int) -> list[dict]:
    conn = pool.connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM shots WHERE episode = %s ORDER BY shot_id", (episode,))
        return [_row_to_dict(r) for r in cur.fetchall()]
    finally:
        pool.release(conn)


def upsert(pool, episode: int, shot_id: str, data: dict):
    conn = pool.connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO shots (episode, shot_id, scene_id, characters, action, dialogue,
                              action_en, dialogue_en, camera, shot_type, duration, emotion, outfit)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (episode, shot_id) DO UPDATE SET
                scene_id=EXCLUDED.scene_id, characters=EXCLUDED.characters,
                action=EXCLUDED.action, dialogue=EXCLUDED.dialogue,
                action_en=EXCLUDED.action_en, dialogue_en=EXCLUDED.dialogue_en
        """, (episode, shot_id, data.get("scene", ""), data.get("characters", ""),
              data.get("action", ""), data.get("dialogue", ""),
              data.get("action_en", ""), data.get("dialogue_en", ""),
              data.get("camera", ""), data.get("shot_type", ""),
              data.get("duration", 0), data.get("emotion", ""), data.get("outfit", "")))
        conn.commit()
    finally:
        pool.release(conn)

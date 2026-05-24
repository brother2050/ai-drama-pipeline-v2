"""镜头数据库操作"""
from __future__ import annotations
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


def get_by_episode(pool, episode: int) -> list[dict]:
    conn = pool.connect()
    try:
        cur = conn.cursor()
        ph = _ph(pool)
        cur.execute(f"SELECT * FROM shots WHERE episode = {ph} ORDER BY shot_id", (episode,))
        return [_row_to_dict(r) for r in cur.fetchall()]
    finally:
        pool.release(conn)


def upsert(pool, episode: int, shot_id: str, data: dict):
    conn = pool.connect()
    try:
        cur = conn.cursor()
        ph = _ph(pool)
        if is_postgres(pool):
            cur.execute(f"""
                INSERT INTO shots (episode, shot_id, scene_id, characters, action, dialogue,
                                  camera, shot_type, duration, emotion, outfit)
                VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                ON CONFLICT (episode, shot_id) DO UPDATE SET
                    scene_id=EXCLUDED.scene_id, characters=EXCLUDED.characters,
                    action=EXCLUDED.action, dialogue=EXCLUDED.dialogue
            """, (episode, shot_id, data.get("scene", ""), data.get("characters", ""),
                  data.get("action", ""), data.get("dialogue", ""),
                  data.get("camera", ""), data.get("shot_type", ""),
                  data.get("duration", 0), data.get("emotion", ""), data.get("outfit", "")))
        else:
            cur.execute(f"""
                INSERT OR REPLACE INTO shots (episode, shot_id, scene_id, characters, action, dialogue,
                                              camera, shot_type, duration, emotion, outfit)
                VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
            """, (episode, shot_id, data.get("scene", ""), data.get("characters", ""),
                  data.get("action", ""), data.get("dialogue", ""),
                  data.get("camera", ""), data.get("shot_type", ""),
                  data.get("duration", 0), data.get("emotion", ""), data.get("outfit", "")))
        conn.commit()
    finally:
        pool.release(conn)

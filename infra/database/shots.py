"""镜头数据库操作 — PostgreSQL"""
from __future__ import annotations


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    if hasattr(row, 'keys'):
        return {k: row[k] for k in row.keys()}
    return {}


def _safe_float(val, default=0.0) -> float:
    """安全的 float 转换，处理 CSV 字符串和非数字值"""
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def get_by_episode(pool, episode: int) -> list[dict]:
    with pool.connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM shots WHERE episode = %s ORDER BY shot_id", (episode,))
        return [_row_to_dict(r) for r in cur.fetchall()]


def upsert(pool, episode: int, shot_id: str, data: dict):
    with pool.connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO shots (episode, shot_id, scene_id, characters, action, dialogue,
                              action_en, dialogue_en, camera, shot_type, duration, emotion, outfit)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (episode, shot_id) DO UPDATE SET
                scene_id=EXCLUDED.scene_id, characters=EXCLUDED.characters,
                action=EXCLUDED.action, dialogue=EXCLUDED.dialogue,
                action_en=EXCLUDED.action_en, dialogue_en=EXCLUDED.dialogue_en,
                camera=EXCLUDED.camera, shot_type=EXCLUDED.shot_type,
                duration=EXCLUDED.duration, emotion=EXCLUDED.emotion, outfit=EXCLUDED.outfit
        """, (episode, shot_id, data.get("scene", ""), data.get("characters", ""),
              data.get("action", ""), data.get("dialogue", ""),
              data.get("action_en", ""), data.get("dialogue_en", ""),
              data.get("camera", ""), data.get("shot_type", ""),
              _safe_float(data.get("duration", 0)), data.get("emotion", ""), data.get("outfit", "")))
        conn.commit()

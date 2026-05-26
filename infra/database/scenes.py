"""场景数据库操作 — PostgreSQL"""
from __future__ import annotations
import json


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    if hasattr(row, 'keys'):
        return {k: row[k] for k in row.keys()}
    return {}


def get_all(pool) -> list[dict]:
    with pool.connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM scenes ORDER BY id")
        return [_row_to_dict(r) for r in cur.fetchall()]


def upsert(pool, scene_id: str, data: dict):
    with pool.connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO scenes (id, name, description, lighting, reference_image, depth_map)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name=EXCLUDED.name, description=EXCLUDED.description,
                lighting=EXCLUDED.lighting, reference_image=EXCLUDED.reference_image,
                depth_map=EXCLUDED.depth_map
        """, (scene_id, data.get("name", ""), data.get("description", ""),
              data.get("lighting", ""), data.get("reference_image", ""),
              data.get("depth_map", "")))
        conn.commit()


def delete(pool, scene_id: str):
    with pool.connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM scenes WHERE id = %s", (scene_id,))
        conn.commit()

"""场景数据库操作"""
from __future__ import annotations
import json

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
        cur.execute("SELECT * FROM scenes ORDER BY id")
        return [_row_to_dict(r) for r in cur.fetchall()]
    finally:
        pool.release(conn)


def upsert(pool, scene_id: str, data: dict):
    conn = pool.connect()
    try:
        cur = conn.cursor()
        ph = _ph(pool)
        if is_postgres(pool):
            cur.execute(f"""
                INSERT INTO scenes (id, name, description, lighting, reference_image, depth_map)
                VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                ON CONFLICT (id) DO UPDATE SET
                    name=EXCLUDED.name, description=EXCLUDED.description,
                    lighting=EXCLUDED.lighting, reference_image=EXCLUDED.reference_image
            """, (scene_id, data.get("name", ""), data.get("description", ""),
                  data.get("lighting", ""), data.get("reference_image", ""),
                  data.get("depth_map", "")))
        else:
            cur.execute(f"""
                INSERT OR REPLACE INTO scenes (id, name, description, lighting, reference_image, depth_map)
                VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph})
            """, (scene_id, data.get("name", ""), data.get("description", ""),
                  data.get("lighting", ""), data.get("reference_image", ""),
                  data.get("depth_map", "")))
        conn.commit()
    finally:
        pool.release(conn)

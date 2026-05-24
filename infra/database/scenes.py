"""场景数据库操作"""
from __future__ import annotations
import json

def get_all(pool) -> list[dict]:
    conn = pool.connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM scenes ORDER BY id")
        return [dict(r) for r in cur.fetchall()]
    finally:
        _release(pool, conn)

def upsert(pool, scene_id: str, data: dict):
    conn = pool.connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO scenes (id, name, description, lighting, reference_image, depth_map)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name=EXCLUDED.name, description=EXCLUDED.description,
                lighting=EXCLUDED.lighting, reference_image=EXCLUDED.reference_image
        """, (scene_id, data.get("name", ""), data.get("description", ""),
              data.get("lighting", ""), data.get("reference_image", ""),
              data.get("depth_map", "")))
        conn.commit()
    finally:
        _release(pool, conn)

def _release(pool, conn):
    if hasattr(pool, 'release'):
        pool.release(conn)
    else:
        conn.close()

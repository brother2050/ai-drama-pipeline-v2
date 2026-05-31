"""场景数据库操作 — PostgreSQL"""
from __future__ import annotations
import json


def _row_to_dict(row) -> dict:
    """将数据库行转为字典，反序列化 JSON 字段"""
    if row is None:
        return {}
    if hasattr(row, 'keys'):
        d = {k: row[k] for k in row.keys()}
        if "reference_images" in d and isinstance(d["reference_images"], str):
            try:
                d["reference_images"] = json.loads(d["reference_images"])
            except (json.JSONDecodeError, TypeError):
                logger.debug(f"{type(e).__name__}: {e}")
        return d
    return {}


def get_all(pool) -> list[dict]:
    with pool.connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT * FROM scenes ORDER BY id")
            return [_row_to_dict(r) for r in cur.fetchall()]
        finally:
            cur.close()


def upsert(pool, scene_id: str, data: dict):
    with pool.connection() as conn:
        cur = conn.cursor()
        try:
            # reference_images 在 YAML 中是 list，需 JSON 序列化后存入 TEXT 字段
            ref_images = data.get("reference_images", [])
            if isinstance(ref_images, list):
                ref_images_json = json.dumps(ref_images, ensure_ascii=False)
            else:
                ref_images_json = ref_images if isinstance(ref_images, str) else "[]"
            cur.execute("""
                INSERT INTO scenes (id, name, description, lighting, reference_images, depth_map)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name=EXCLUDED.name, description=EXCLUDED.description,
                    lighting=EXCLUDED.lighting, reference_images=EXCLUDED.reference_images,
                    depth_map=EXCLUDED.depth_map
            """, (scene_id, data.get("name", ""), data.get("description", ""),
                  data.get("lighting", ""), ref_images_json,
                  data.get("depth_map", "")))
            conn.commit()
        finally:
            cur.close()


def delete(pool, scene_id: str):
    with pool.connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM scenes WHERE id = %s", (scene_id,))
            conn.commit()
        finally:
            cur.close()

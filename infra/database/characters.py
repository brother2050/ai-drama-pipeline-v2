"""角色数据库操作 — PostgreSQL"""
from __future__ import annotations
import json


def _row_to_dict(row) -> dict:
    """将数据库行转为字典，反序列化 JSON 字段"""
    if row is None:
        return {}
    if hasattr(row, 'keys'):
        d = {k: row[k] for k in row.keys()}
        for json_field in ("voice_config", "reference_images", "outfits"):
            if json_field in d and isinstance(d[json_field], str):
                try:
                    d[json_field] = json.loads(d[json_field])
                except (json.JSONDecodeError, TypeError):
                    logger.debug(f"{type(e).__name__}: {e}")
        return d
    return {}


def get_all(pool) -> list[dict]:
    with pool.connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT * FROM characters ORDER BY id")
            return [_row_to_dict(r) for r in cur.fetchall()]
        finally:
            cur.close()


def get_by_id(pool, char_id: str) -> dict | None:
    with pool.connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT * FROM characters WHERE id = %s", (char_id,))
            row = cur.fetchone()
            return _row_to_dict(row) if row else None
        finally:
            cur.close()


def upsert(pool, char_id: str, data: dict):
    with pool.connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO characters (id, name, gender, personality, appearance, outfits, voice_config, reference_images)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name=EXCLUDED.name, gender=EXCLUDED.gender, personality=EXCLUDED.personality,
                    appearance=EXCLUDED.appearance, outfits=EXCLUDED.outfits,
                    voice_config=EXCLUDED.voice_config, reference_images=EXCLUDED.reference_images
            """, (char_id, data.get("name", ""), data.get("gender", ""),
                  data.get("personality", ""), data.get("appearance", ""),
                  json.dumps(data.get("outfits", []), ensure_ascii=False),
                  json.dumps(data.get("voice", {}), ensure_ascii=False),
                  json.dumps(data.get("reference_images", []), ensure_ascii=False)))
            conn.commit()
        finally:
            cur.close()


def delete(pool, char_id: str):
    with pool.connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM characters WHERE id = %s", (char_id,))
            conn.commit()
        finally:
            cur.close()

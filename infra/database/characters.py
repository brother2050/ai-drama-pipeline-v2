"""角色数据库操作"""
from __future__ import annotations
import json
from typing import Any

def get_all(pool) -> list[dict]:
    conn = pool.connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM characters ORDER BY id")
        rows = cur.fetchall()
        return [dict(r) if hasattr(r, 'keys') else _row_to_dict(r) for r in rows]
    finally:
        _release(pool, conn)

def get_by_id(pool, char_id: str) -> dict | None:
    conn = pool.connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM characters WHERE id = %s", (char_id,))
        row = cur.fetchone()
        return dict(row) if row and hasattr(row, 'keys') else None
    finally:
        _release(pool, conn)

def upsert(pool, char_id: str, data: dict):
    conn = pool.connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO characters (id, name, appearance, voice_config, reference_images)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name=EXCLUDED.name, appearance=EXCLUDED.appearance,
                voice_config=EXCLUDED.voice_config, reference_images=EXCLUDED.reference_images
        """, (char_id, data.get("name", ""), data.get("appearance", ""),
              json.dumps(data.get("voice", {}), ensure_ascii=False),
              json.dumps(data.get("reference_images", []), ensure_ascii=False)))
        conn.commit()
    finally:
        _release(pool, conn)

def _row_to_dict(row):
    if hasattr(row, 'keys'):
        return dict(row)
    return {}

def _release(pool, conn):
    if hasattr(pool, 'release'):
        pool.release(conn)
    else:
        conn.close()

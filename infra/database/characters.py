"""角色数据库操作 — PostgreSQL"""
from __future__ import annotations
import json
from typing import Any


def _row_to_dict(row) -> dict:
    """将数据库行转为字典"""
    if row is None:
        return {}
    if hasattr(row, 'keys'):
        return {k: row[k] for k in row.keys()}
    return {}


def get_all(pool) -> list[dict]:
    conn = pool.connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM characters ORDER BY id")
        return [_row_to_dict(r) for r in cur.fetchall()]
    finally:
        pool.release(conn)


def get_by_id(pool, char_id: str) -> dict | None:
    conn = pool.connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM characters WHERE id = %s", (char_id,))
        row = cur.fetchone()
        return _row_to_dict(row) if row else None
    finally:
        pool.release(conn)


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
        pool.release(conn)


def delete(pool, char_id: str):
    conn = pool.connect()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM characters WHERE id = %s", (char_id,))
        conn.commit()
    finally:
        pool.release(conn)

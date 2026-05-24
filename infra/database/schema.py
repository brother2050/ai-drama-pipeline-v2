"""数据库 Schema"""
from __future__ import annotations

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS characters (
    id TEXT PRIMARY KEY,
    name TEXT,
    appearance TEXT,
    voice_config TEXT,
    reference_images TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scenes (
    id TEXT PRIMARY KEY,
    name TEXT,
    description TEXT,
    lighting TEXT,
    reference_image TEXT,
    depth_map TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS episodes (
    episode INTEGER PRIMARY KEY,
    title TEXT,
    status TEXT DEFAULT 'pending',
    shot_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS shots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode INTEGER,
    shot_id TEXT,
    scene_id TEXT,
    characters TEXT,
    action TEXT,
    dialogue TEXT,
    camera TEXT,
    shot_type TEXT,
    duration REAL,
    emotion TEXT,
    outfit TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(episode, shot_id)
);

CREATE TABLE IF NOT EXISTS generation_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode INTEGER,
    shot_id TEXT,
    stage TEXT,
    status TEXT DEFAULT 'pending',
    path TEXT,
    error TEXT,
    elapsed REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(episode, shot_id, stage)
);
"""


def init_schema(conn):
    """初始化数据库 Schema"""
    cursor = conn.cursor()
    for stmt in SCHEMA_SQL.split(";"):
        stmt = stmt.strip()
        if stmt:
            cursor.execute(stmt)
    conn.commit()

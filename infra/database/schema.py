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
    reference_images TEXT,
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
    id SERIAL PRIMARY KEY,
    episode INTEGER,
    shot_id TEXT,
    scene_id TEXT,
    characters TEXT,
    action TEXT,
    dialogue TEXT,
    action_en TEXT DEFAULT '',
    dialogue_en TEXT DEFAULT '',
    camera TEXT,
    shot_type TEXT,
    duration REAL,
    emotion TEXT,
    outfit TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(episode, shot_id)
);

CREATE TABLE IF NOT EXISTS generation_status (
    id SERIAL PRIMARY KEY,
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

CREATE TABLE IF NOT EXISTS comfyui_assets (
    id SERIAL PRIMARY KEY,
    project_dir TEXT NOT NULL,
    server_url TEXT NOT NULL,
    asset_type TEXT NOT NULL CHECK (asset_type IN ('image', 'lora')),
    filename TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_dir, server_url, asset_type, filename)
);
"""


def init_schema(conn):
    """初始化数据库 Schema"""
    cursor = conn.cursor()
    try:
        for stmt in SCHEMA_SQL.split(";"):
            stmt = stmt.strip()
            if stmt:
                cursor.execute(stmt)
        conn.commit()
    finally:
        cursor.close()

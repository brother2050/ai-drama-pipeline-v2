"""数据库 Schema"""
from __future__ import annotations

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS characters (
    id TEXT PRIMARY KEY,
    name TEXT,
    gender TEXT DEFAULT '',
    personality TEXT DEFAULT '',
    appearance TEXT,
    outfits TEXT,
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
    """初始化数据库 Schema（含自动迁移）"""
    cursor = conn.cursor()
    try:
        # 1. 创建表（IF NOT EXISTS 保证幂等）
        for stmt in SCHEMA_SQL.split(";"):
            stmt = stmt.strip()
            if stmt:
                cursor.execute(stmt)

        # 2. 自动迁移：scenes.reference_image → reference_images
        _migrate_scenes_reference_images(cursor)
        # 3. 自动迁移：characters 表添加缺失列
        _migrate_characters_columns(cursor)

        conn.commit()
    finally:
        cursor.close()


def _migrate_scenes_reference_images(cursor) -> None:
    """迁移 scenes 表的 reference_image 列名为 reference_images

    旧版 schema 使用 reference_image（单数），新版改为 reference_images（复数/JSON）。
    使用 ALTER TABLE RENAME COLUMN（PostgreSQL 10+），已迁移时静默跳过。
    """
    try:
        # 检查旧列是否存在
        cursor.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'scenes' AND column_name = 'reference_image'
        """)
        if cursor.fetchone():
            cursor.execute("ALTER TABLE scenes RENAME COLUMN reference_image TO reference_images")
    except Exception:
        # 列已迁移或表不存在，静默跳过
        pass


def _migrate_characters_columns(cursor) -> None:
    """迁移 characters 表：添加 gender, personality, outfits 列"""
    for col, col_type in [("gender", "TEXT DEFAULT ''"), ("personality", "TEXT DEFAULT ''"), ("outfits", "TEXT")]:
        try:
            cursor.execute(f"""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'characters' AND column_name = '{col}'
            """)
            if not cursor.fetchone():
                cursor.execute(f"ALTER TABLE characters ADD COLUMN {col} {col_type}")
        except Exception:
            pass

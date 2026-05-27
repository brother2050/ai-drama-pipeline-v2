"""ComfyUI 资源跟踪 — PostgreSQL 持久化

跟踪哪些文件已上传到哪些 ComfyUI 服务器，避免重复上传或遗漏。
"""
from __future__ import annotations


def check(pool, project_dir: str, server_url: str, asset_type: str, filename: str) -> bool:
    """检查资产是否已记录存在于此服务器"""
    with pool.connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM comfyui_assets "
            "WHERE project_dir = %s AND server_url = %s AND asset_type = %s AND filename = %s",
            (project_dir, server_url, asset_type, filename),
        )
        return cur.fetchone() is not None


def mark(pool, project_dir: str, server_url: str, asset_type: str, filename: str):
    """记录资产已存在于此服务器"""
    with pool.connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO comfyui_assets (project_dir, server_url, asset_type, filename) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (project_dir, server_url, asset_type, filename) DO NOTHING",
            (project_dir, server_url, asset_type, filename),
        )
        conn.commit()


def unmark(pool, project_dir: str, server_url: str, asset_type: str, filename: str):
    """移除资产记录（如文件被删除）"""
    with pool.connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM comfyui_assets "
            "WHERE project_dir = %s AND server_url = %s AND asset_type = %s AND filename = %s",
            (project_dir, server_url, asset_type, filename),
        )
        conn.commit()


def list_assets(pool, project_dir: str, server_url: str | None = None) -> list[dict]:
    """列出项目的全部/指定服务器的资产"""
    with pool.connection() as conn:
        cur = conn.cursor()
        if server_url:
            cur.execute(
                "SELECT asset_type, filename FROM comfyui_assets "
                "WHERE project_dir = %s AND server_url = %s ORDER BY asset_type, filename",
                (project_dir, server_url),
            )
        else:
            cur.execute(
                "SELECT asset_type, filename FROM comfyui_assets "
                "WHERE project_dir = %s ORDER BY asset_type, filename",
                (project_dir,),
            )
        return [{"asset_type": r[0], "filename": r[1]} for r in cur.fetchall()]


def delete_by_project(pool, project_dir: str):
    """删除项目的所有资产记录（项目被删除时清理）"""
    with pool.connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM comfyui_assets WHERE project_dir = %s", (project_dir,))
        conn.commit()

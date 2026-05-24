"""文本工具"""
from __future__ import annotations

def truncate(s: str, max_len: int = 100) -> str:
    return s[:max_len] + "..." if len(s) > max_len else s

def sanitize_filename(name: str) -> str:
    import re
    return re.sub(r'[<>:"/\\|?*]', '_', name).strip()

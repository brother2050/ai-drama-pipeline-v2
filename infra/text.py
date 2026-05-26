"""文本工具"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def truncate(s: str, max_len: int = 100) -> str:
    if not s:
        return ""
    if len(s) <= max_len:
        return s
    return s[:max(0, max_len - 3)] + "..."

def sanitize_filename(name: str) -> str:
    import re
    if not name:
        return ""
    return re.sub(r'[<>:"/\\|?*]', '_', str(name)).strip()

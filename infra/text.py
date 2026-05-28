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
    result = re.sub(r'[<>:"/\\|?*]', '_', str(name)).strip()
    # 限制长度为 200 字节（留余量给扩展名，文件系统限制 255 字节）
    if len(result.encode("utf-8")) > 200:
        while len(result.encode("utf-8")) > 200 and result:
            result = result[:-1]
    return result

"""JSON 解析工具 — 统一的 LLM 输出解析器

提供容错的 JSON 解析能力，支持：
- markdown 代码块提取
- 前后多余文字过滤
- 截断 JSON 自动修复（LLM 输出因 token 限制被截断）
- 单引号 / Python dict 风格兼容
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

__all__ = ["parse_llm_json"]


def _repair_truncated_json(text: str) -> str | None:
    """尝试修复被截断的 JSON（LLM 输出常因 token 限制被截断）

    策略：逐字符跟踪 JSON 结构深度，遇到截断时补全缺失的闭合括号。
    """
    if not text:
        return None

    text = text.rstrip()
    if not text:
        return None

    # 去掉末尾可能的不完整内容（如截断在逗号、冒号、值中间）
    cleaned = text.rstrip(", \t\n\r")

    # 尝试直接解析清理后的文本
    try:
        json.loads(cleaned)
        return cleaned
    except json.JSONDecodeError:
        pass

    # 逐字符跟踪结构，找到最后一个合法位置
    stack = []  # 记录未闭合的括号: '[' 或 '{'
    in_string = False
    escape = False
    last_safe = -1  # 最后一个合法的字符位置

    for i, ch in enumerate(cleaned):
        if escape:
            escape = False
            continue
        if ch == '\\' and in_string:
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue

        if ch == '[':
            stack.append(']')
        elif ch == '{':
            stack.append('}')
        elif ch in (']', '}'):
            if stack and stack[-1] == ch:
                stack.pop()
                last_safe = i
        elif ch == ',':
            if not stack:
                last_safe = i

    # 情况1：完整 JSON，只是末尾有垃圾
    if not stack and last_safe >= 0:
        candidate = cleaned[:last_safe + 1]
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    # 情况2：JSON 被截断，需要补全闭合括号
    if stack:
        candidate = cleaned

        # 如果末尾在字符串中间，截断到上一个完整 token
        if in_string:
            for j in range(len(candidate) - 1, -1, -1):
                if candidate[j] in (',', '[', '{'):
                    candidate = candidate[:j + 1]
                    break
            else:
                candidate = ""

        # 去掉末尾的不完整键值
        candidate = candidate.rstrip(", \t\n\r")
        if candidate.endswith(':'):
            candidate = candidate[:-1].rstrip(", \t\n\r")

        # 补全所有未闭合的括号
        closing = ''.join(reversed(stack))
        repaired = candidate + closing

        try:
            json.loads(repaired)
            return repaired
        except json.JSONDecodeError:
            # 逐字符回退找到合法位置
            for j in range(len(candidate) - 1, max(0, len(candidate) - 200), -1):
                if candidate[j] in (',',):
                    attempt = candidate[:j] + closing
                    try:
                        json.loads(attempt)
                        return attempt
                    except json.JSONDecodeError:
                        continue

    return None


def parse_llm_json(text: str):
    """从 LLM 响应中提取 JSON（容错：markdown 代码块、前后多余文字、截断修复）

    Args:
        text: LLM 原始响应文本

    Returns:
        解析后的对象，或 None 表示解析失败
    """
    if not text:
        return None
    text = text.strip()

    # 1. 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. 提取 markdown 代码块（```json ... ``` 或 ``` ... ```）
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. 提取第一个完整 JSON 数组/对象（深度匹配，非贪婪）
    for start_ch, end_ch in [('[', ']'), ('{', '}')]:
        idx = text.find(start_ch)
        if idx < 0:
            continue
        depth = 0
        in_str = False
        escape = False
        for i in range(idx, len(text)):
            c = text[i]
            if escape:
                escape = False
                continue
            if c == '\\' and in_str:
                escape = True
                continue
            if c == '"' and not escape:
                in_str = not in_str
                continue
            if in_str:
                continue
            if c == start_ch:
                depth += 1
            elif c == end_ch:
                depth -= 1
                if depth == 0:
                    candidate = text[idx:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        # 尝试去掉尾随逗号
                        fixed = re.sub(r',\s*([\]}])', r'\1', candidate)
                        try:
                            return json.loads(fixed)
                        except json.JSONDecodeError:
                            break

    # 4. 单引号 → 双引号（Python 风格 dict → JSON）
    if "'" in text and '"' not in text:
        try:
            import ast
            return ast.literal_eval(text)
        except (ValueError, SyntaxError):
            pass

    # 5. 截断修复：LLM 输出因 token 限制被截断时，尝试补全闭合括号
    for start_ch in ('[', '{'):
        idx = text.find(start_ch)
        if idx != -1:
            repaired = _repair_truncated_json(text[idx:])
            if repaired is not None:
                try:
                    return json.loads(repaired)
                except json.JSONDecodeError:
                    pass

    # 6. 全文修复（兜底）
    repaired = _repair_truncated_json(text)
    if repaired is not None:
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

    logger.warning(f"无法从 LLM 回复中提取 JSON（前 200 字）: {text[:200]}")
    return None

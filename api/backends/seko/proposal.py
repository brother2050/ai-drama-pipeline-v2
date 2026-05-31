"""Seko API 后端 — 影视策划案生成/查询/修改 + 图片下载

集成 seko.sensetime.com 的策划案相关功能，不含视频生产接口。
"""
from __future__ import annotations

import http.client
import json
import logging
import os
import time
import urllib.parse
import urllib.request
from collections.abc import Callable

logger = logging.getLogger(__name__)

_API_BASE = "seko.sensetime.com"


def _get_api_key(config: dict | None = None) -> str:
    """获取 Seko API Key（参数 > 环境变量）"""
    if config and config.get("api_key"):
        return config["api_key"]
    return os.environ.get("SEKO_API_KEY", "")


# ══════════════════════════════════════════════════════════
# 策划案生成
# ══════════════════════════════════════════════════════════

def generate_proposal(prompt: str, *, api_key: str = "", config: dict | None = None) -> dict:
    """生成影视策划案

    Args:
        prompt: 策划案描述/故事梗概
        api_key: Seko API Key（可选，默认从环境变量读取）
        config: 后端配置字典

    Returns:
        API 响应字典，包含 taskId 等信息
    """
    key = api_key or _get_api_key(config)
    if not key:
        return {"code": 500, "msg": "SEKO_API_KEY 未配置"}

    api_base = _API_BASE
    conn = http.client.HTTPSConnection(api_base, timeout=30)
    payload = json.dumps({"input": prompt})
    headers = {
        "Seko-API-Key": key,
        "Content-Type": "application/json",
        "Accept": "*/*",
    }
    try:
        conn.request("POST", "/seko-api/openapi/v1/plan-tasks", payload, headers)
        res = conn.getresponse()
        data = res.read()
        return json.loads(data.decode("utf-8"))
    except Exception as e:
        logger.error(f"生成策划案失败: {e}", exc_info=True)
        return {"code": 500, "msg": str(e)}
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════
# 策划案状态查询
# ══════════════════════════════════════════════════════════

def check_proposal_status(task_id: str, *, api_key: str = "", config: dict | None = None) -> dict:
    """查询策划案任务状态（单次查询，不轮询）

    Args:
        task_id: 任务 ID
        api_key: Seko API Key
        config: 后端配置字典

    Returns:
        API 响应字典
    """
    key = api_key or _get_api_key(config)
    if not key:
        return {"code": 500, "msg": "SEKO_API_KEY 未配置"}

    api_base = _API_BASE
    conn = http.client.HTTPSConnection(api_base, timeout=30)
    headers = {
        "Seko-API-Key": key,
        "Accept": "*/*",
    }
    try:
        endpoint = f"/seko-api/openapi/v1/plan-tasks/{task_id}/status"
        conn.request("GET", endpoint, "", headers)
        res = conn.getresponse()
        data = res.read()
        return json.loads(data.decode("utf-8"))
    except Exception as e:
        return {"code": 500, "msg": str(e)}
    finally:
        conn.close()


def wait_for_proposal(
    task_id: str,
    *,
    api_key: str = "",
    config: dict | None = None,
    interval: int = 10,
    max_retries: int = 180,
    on_status: Callable[[str], None] | None = None,
) -> dict:
    """轮询等待策划案任务完成

    Args:
        task_id: 任务 ID
        api_key: Seko API Key
        config: 后端配置字典
        interval: 轮询间隔（秒）
        max_retries: 最大轮询次数（默认 180 次 × 10 秒 = 30 分钟）
        on_status: 状态回调 fn(status: str)

    Returns:
        最终 API 响应字典
    """
    logger.info(f"等待策划案完成，taskId: {task_id}，每 {interval} 秒轮询一次（最多 {max_retries} 次）...")
    for attempt in range(1, max_retries + 1):
        result = check_proposal_status(task_id, api_key=api_key, config=config)
        if result.get("code") != 200:
            return result

        data = result.get("data", {})
        status = data.get("taskStatus", "RUNNING")
        if on_status:
            on_status(status)

        if status == "RUNNING":
            time.sleep(interval)
        else:
            if status == "OK":
                logger.info("策划案任务成功完成！")
            elif status == "FAIL":
                logger.warning(f"策划案任务失败: {data.get('taskStatusMsg', '未知原因')}")
            return result

    logger.warning(f"策划案轮询超时（{max_retries} 次），taskId: {task_id}")
    return {"code": 408, "msg": f"轮询超时（{max_retries} 次）", "data": {"taskStatus": "TIMEOUT"}}


# ══════════════════════════════════════════════════════════
# 策划案修改
# ══════════════════════════════════════════════════════════

def modify_proposal(
    task_id: str,
    prompt: str,
    *,
    api_key: str = "",
    config: dict | None = None,
) -> dict:
    """修改已有策划案

    Args:
        task_id: 原策划案任务 ID
        prompt: 修改指令
        api_key: Seko API Key
        config: 后端配置字典

    Returns:
        API 响应字典，包含新 taskId
    """
    key = api_key or _get_api_key(config)
    if not key:
        return {"code": 500, "msg": "SEKO_API_KEY 未配置"}

    api_base = _API_BASE
    conn = http.client.HTTPSConnection(api_base, timeout=30)
    payload = json.dumps({
        "input": prompt,
        "updateCtx": {"taskId": task_id},
    })
    headers = {
        "Seko-API-Key": key,
        "Content-Type": "application/json",
        "Accept": "*/*",
    }
    try:
        conn.request("POST", "/seko-api/openapi/v1/plan-tasks", payload, headers)
        res = conn.getresponse()
        data = res.read()
        return json.loads(data.decode("utf-8"))
    except Exception as e:
        logger.error(f"修改策划案失败: {e}", exc_info=True)
        return {"code": 500, "msg": str(e)}
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════
# 图片下载
# ══════════════════════════════════════════════════════════

def download_image(url: str, output_path: str) -> str:
    """下载图片到指定路径

    Args:
        url: 图片 URL
        output_path: 输出目录或文件路径

    Returns:
        实际保存的文件路径
    """
    parsed_url = urllib.parse.urlparse(url)
    filename = os.path.basename(parsed_url.path) or "downloaded_image.png"

    if os.path.isdir(output_path) or not os.path.splitext(output_path)[1]:
        os.makedirs(output_path, exist_ok=True)
        output_path = os.path.join(output_path, filename)
    else:
        parent_dir = os.path.dirname(output_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; ai-drama-pipeline/2.0)"},
    )
    with urllib.request.urlopen(req, timeout=60) as response, open(output_path, "wb") as out_file:
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            out_file.write(chunk)

    logger.info(f"图片下载成功: {output_path}")
    return output_path


def download_elements_images(data: dict, download_dir: str) -> list[str]:
    """下载策划案返回 JSON 中的所有 elements 图片

    Args:
        data: API 响应的 data 字段
        download_dir: 下载目录

    Returns:
        已下载的文件路径列表
    """
    result_obj = data.get("result", {})
    elements = result_obj.get("elements", [])
    if not elements:
        logger.info("未发现可下载的 elements 图片。")
        return []

    os.makedirs(download_dir, exist_ok=True)
    downloaded = []

    for element in elements:
        url = element.get("elementUrl")
        name = element.get("elementName")
        if not url or not name:
            continue

        parsed_url = urllib.parse.urlparse(url)
        ext = os.path.splitext(parsed_url.path)[1] or ".jpeg"
        safe_name = "".join(c for c in name if c.isalnum() or c in (" ", "-", "_")).strip()
        filename = f"{safe_name}{ext}"
        filepath = os.path.join(download_dir, filename)

        try:
            download_image(url, filepath)
            downloaded.append(filepath)
        except Exception as e:
            logger.warning(f"下载失败 {name}: {e}")

    return downloaded

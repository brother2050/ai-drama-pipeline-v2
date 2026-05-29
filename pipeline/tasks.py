"""Celery 任务定义 — 每步独立，按需执行"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import re
import sys
import time
import zlib
from pathlib import Path

import yaml

from pipeline.celery_app import app
from infra.json_parse import parse_llm_json

try:
    from celery.exceptions import SoftTimeLimitException
except ImportError:
    # 兼容部分 Celery 版本
    SoftTimeLimitException = type("SoftTimeLimitException", (BaseException,), {})

logger = logging.getLogger(__name__)


def _ensure_path():
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _safe_int(val, default=0) -> int:
    """安全的 int 转换，处理空字符串和非数字值"""
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _load_shots(config_path: str, episode: int) -> list[dict]:
    sb = Path(config_path).resolve().parent.parent / "storyboard" / "episodes.csv"
    if not sb.exists():
        return []
    with open(sb, encoding="utf-8") as f:
        return [dict(r) for r in csv.DictReader(f) if _safe_int(r.get("episode", 0)) == episode]


def _find_shot(config_path: str, episode: int, shot_id: str) -> dict | None:
    sb = Path(config_path).resolve().parent.parent / "storyboard" / "episodes.csv"
    if not sb.exists():
        return None
    with open(sb, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if _safe_int(r.get("episode", 0)) == episode and r.get("shot_id") == shot_id:
                return dict(r)
    return None


def _shot_dir(config_path: str, episode: int, shot_id: str) -> Path:
    return _cfg_dir(config_path, "output", f"e{episode:02d}", f"s{shot_id}")


def _check_available(tool_name: str, config_path: str) -> tuple[bool, str]:
    from infra.config import Config
    from infra.toolcheck import check_tool
    result = check_tool(tool_name, Config(config_path).data)
    return result["available"], result.get("reason", "")


def _db_record_step(config_path: str, episode: int, shot_id: str, step: str, result: dict) -> None:
    try:
        from infra.database.pool import get_pool
        from infra.database.generation import upsert_status
        upsert_status(get_pool(), episode, shot_id, step,
                      status=result.get("status", "unknown"), path=result.get("path", ""),
                      error=result.get("reason", "") if result.get("status") in ("skipped", "error") else "",
                      elapsed=result.get("elapsed", 0.0))
    except Exception as e:
        logger.debug(f"DB 写入跳过: {e}")


def _check_step_running(config_path: str, episode: int, shot_id: str, step: str) -> bool:
    try:
        from infra.database.pool import get_pool
        from infra.database.generation import get_shot_status
        return any(s.get("stage") == step and s.get("status") == "running"
                   for s in get_shot_status(get_pool(), episode, shot_id))
    except Exception:
        return False


def _db_mark_running(config_path: str, episode: int, shot_id: str, step: str) -> None:
    try:
        from infra.database.pool import get_pool
        from infra.database.generation import upsert_status
        upsert_status(get_pool(), episode, shot_id, step, status="running")
    except Exception as e:
        logger.debug(f"DB mark_running 跳过: {e}")


def _try_mark_running_atomic(config_path: str, episode: int, shot_id: str, step: str) -> bool:
    """原子操作：检查步骤是否正在运行，如果没有则标记为 running。

    使用 pg_try_advisory_lock + SELECT FOR UPDATE 实现真正的互斥。
    Returns True if successfully marked, False if already running.
    """
    try:
        from infra.database.pool import get_pool, placeholder
        pool = get_pool()
        lock_key = zlib.crc32(f"gen:{episode}:{shot_id}:{step}".encode()) & 0x7FFFFFFF
        with pool.connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute("SELECT pg_try_advisory_lock(%s)", (lock_key,))
                locked = cur.fetchone()[0]
                if not locked:
                    return False
                try:
                    # 查询当前状态，FOR UPDATE 防止并发修改
                    cur.execute(f"""
                        SELECT status, EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - updated_at))
                        FROM generation_status
                        WHERE episode = {placeholder()} AND shot_id = {placeholder()} AND stage = {placeholder()}
                        FOR UPDATE
                    """, (episode, shot_id, step))
                    row = cur.fetchone()
                    if row:
                        status, age = row[0], row[1] or 0
                        if status == "running" and age < 600:
                            return False
                        cur.execute(f"""
                            UPDATE generation_status SET status='running', updated_at=CURRENT_TIMESTAMP
                            WHERE episode={placeholder()} AND shot_id={placeholder()} AND stage={placeholder()}
                        """, (episode, shot_id, step))
                    else:
                        cur.execute(f"""
                            INSERT INTO generation_status (episode, shot_id, stage, status, updated_at)
                            VALUES ({placeholder()}, {placeholder()}, {placeholder()}, 'running', CURRENT_TIMESTAMP)
                        """, (episode, shot_id, step))
                    conn.commit()
                    return True
                finally:
                    # 确保 advisory lock 总是被释放
                    try:
                        cur.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))
                    except Exception:
                        pass
            finally:
                cur.close()
    except Exception:
        # 数据库不可用时回退到非原子版本
        # 注意: _check_step_running 不检查 updated_at，崩溃的任务可能永久阻塞
        # 这里直接放行，依赖 _prepare 后续的工具检查和任务逻辑兜底
        try:
            _db_mark_running(config_path, episode, shot_id, step)
        except Exception:
            pass  # 数据库完全不可用时忽略
        return True


# ══════════════════════════════════════════════════════════
#  公共前置检查
# ══════════════════════════════════════════════════════════

def _prepare(config_path: str, episode: int, shot_id: str, step: str, tool: str, *, need_shot: bool = True, force: bool = False):
    """防重复 → 工具可用 → 查镜头 → 标记运行 → 返回 (cfg, cont, shot, err)"""
    _ensure_path()
    # force=True 时跳过 running 状态检查，允许强制覆盖
    if not force and not _try_mark_running_atomic(config_path, episode, shot_id, step):
        return None, None, None, _skip(shot_id, step, "该步骤正在执行中")
    if force:
        _db_mark_running(config_path, episode, shot_id, step)
    ok, reason = _check_available(tool, config_path)
    if not ok:
        # 回滚 running 状态，否则该步骤 10 分钟内无法重试
        _db_record_step(config_path, episode, shot_id, step, {"status": "skipped", "reason": reason})
        return None, None, None, _skip(shot_id, step, f"{tool} 不可用: {reason}")
    shot = _find_shot(config_path, episode, shot_id) if need_shot else None
    if need_shot and not shot:
        _db_record_step(config_path, episode, shot_id, step, {"status": "error", "reason": "镜头不存在"})
        return None, None, None, _err(shot_id, step, "镜头不存在")
    from infra.config import Config
    from api.registry import Container
    from api import _ensure_registered; _ensure_registered()
    cfg = Config(config_path)
    return cfg, Container(cfg.data), shot, None


def _load_episode_shots(config_path: str, episode: int) -> list[dict] | None:
    """加载指定集的镜头列表，为空时返回 None"""
    shots = _load_shots(config_path, episode)
    return shots if shots else None


def _skip(shot_id, step, reason): return {"shot_id": shot_id, "step": step, "status": "skipped", "reason": reason}
def _err(shot_id, step, reason): return {"shot_id": shot_id, "step": step, "status": "error", "reason": reason}
def _done(shot_id, step, path, **kw): return {"shot_id": shot_id, "step": step, "status": "done", "path": path, **kw}


def _init_ctx(config_path: str):
    """初始化通用上下文: ensure_path + Config + Container（用于非 _prepare 的任务）"""
    _ensure_path()
    from infra.config import Config
    from api import _ensure_registered; _ensure_registered()
    from api.registry import Container
    cfg = Config(config_path)
    return cfg, Container(cfg.data)


def _cfg_dir(config_path: str, *parts) -> Path:
    """获取项目目录下的子路径"""
    from infra.config import Config
    p = Path(Config(config_path).project_dir)
    return p.joinpath(*parts) if parts else p


def _unique_hash_id(prefix: str, name: str, existing: dict) -> str:
    """基于名字生成确定性短 hash ID，碰撞时自动追加后缀

    Args:
        prefix: ID 前缀（如 "ch"、"sc"）
        name: 角色/场景名（任意语言）
        existing: 已有的 id_remap，用于检测碰撞

    Returns:
        唯一的 hash ID，如 ch_8a3f2b1c 或 ch_8a3f2b1c_2
    """
    h = hashlib.md5(name.encode("utf-8")).hexdigest()[:8]
    base = f"{prefix}_{h}"
    candidate = base
    counter = 2
    # 检查碰撞：id_remap 中值已存在 且 不是自己
    while candidate in existing.values():
        candidate = f"{base}_{counter}"
        counter += 1
    return candidate


# ══════════════════════════════════════════════════════════
#  核心逻辑函数（可被 preview.py 等模块复用）
# ══════════════════════════════════════════════════════════

def tts_core(shot_id: str, shot: dict, cfg, cont, out_dir: Path, *, force: bool = False) -> dict:
    """TTS 核心逻辑 — 合成台词为音频

    Args:
        shot_id: 镜头 ID
        shot: 镜头数据
        cfg: Config 对象
        cont: DI 容器
        out_dir: 输出目录
        force: True 时覆盖已有文件，False 时跳过

    Returns:
        {"status": "done"/"skipped"/"error", ...}
    """
    dialogue = shot.get("dialogue", "").strip()
    if not dialogue or dialogue == "......":
        return _skip(shot_id, "tts", "无台词")

    out_dir.mkdir(parents=True, exist_ok=True)
    audio_path = str(out_dir / "audio.wav")

    # 已有文件且非强制模式 → 跳过
    if not force and Path(audio_path).exists():
        return _skip(shot_id, "tts", "音频已存在")

    char_ids = [c.strip() for c in shot.get("characters", "").split("+") if c.strip()]
    from engines.shot_manager import ShotManager
    sm = ShotManager(str(Path(cfg.project_dir) / "storyboard" / "episodes.csv"),
                     str(Path(cfg.project_dir) / "config"))
    char_data = sm.get_character(char_ids[0]) if char_ids else {}
    if char_ids and not char_data:
        logger.warning(f"[{shot_id}] 角色 {char_ids[0]} 不存在，使用默认声音")
    voice_config = char_data.get("voice", {})
    emotion = shot.get("emotion", "neutral")
    language = shot.get("language", "zh")

    try:
        cont.get("tts").synthesize(dialogue, audio_path, voice_config=voice_config,
                                   emotion=emotion, language=language)
    except Exception as e:
        return _err(shot_id, "tts", f"TTS 合成失败: {e}")
    return _done(shot_id, "tts", audio_path)


def first_frame_core(shot_id: str, shot: dict, cfg, cont, out_dir: Path, *, force: bool = False) -> dict:
    """首帧生成核心逻辑 — ComfyUI 工作流构建 + 执行

    Args:
        shot_id: 镜头 ID
        shot: 镜头数据
        cfg: Config 对象
        cont: DI 容器
        out_dir: 输出目录
        force: True 时覆盖已有文件，False 时跳过

    Returns:
        {"status": "done"/"error", ...}
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # 已有文件且非强制模式 → 跳过
    frame_path = out_dir / "frame.png"
    if not force and frame_path.exists():
        return _skip(shot_id, "first_frame", "首帧已存在")

    from engines.shot_manager import ShotManager
    from engines.workflow_builder import WorkflowBuilder
    from engines.prompt import translate_to_english
    from engines.multi_char import MultiCharacterHandler

    char_ids = [c.strip() for c in shot.get("characters", "").split("+") if c.strip()]
    sm = ShotManager(str(Path(cfg.project_dir) / "storyboard" / "episodes.csv"),
                     str(Path(cfg.project_dir) / "config"))

    # LLM 仅在预翻译字段缺失时使用（准备阶段已翻译则不需要）
    llm = None
    try:
        if cfg.get("llm", {}).get("enabled"):
            llm = cont.get("llm")
    except Exception:
        pass

    # 优先读视角专属描述，回退到通用 appearance_en
    from engines.prompt import get_view_appearance
    shot_type = shot.get("shot_type", "")
    char_descs = []
    for cid in char_ids:
        char = sm.get_character(cid)
        if char:
            desc_en = get_view_appearance(char, shot_type) or char.get("appearance_en", "")
            if desc_en:
                char_descs.append(desc_en)
            else:
                char_descs.append(translate_to_english(char.get("appearance", ""), llm=llm))

    # 优先读预翻译的 description_en，无则回退到翻译
    scene = sm.get_scene(shot.get("scene", ""))
    if scene:
        scene_desc = scene.get("description_en", "") or translate_to_english(scene.get("description", ""), llm=llm)
    else:
        scene_desc = ""

    multi_char_prompt = ""
    if len(char_ids) > 1:
        multi_char_prompt = MultiCharacterHandler().generate_multi_char_prompt(
            [c for c in (sm.get_character(cid) for cid in char_ids) if c])

    wb = WorkflowBuilder(cfg.data, cfg.get("models", {}), cfg.project_dir, comfyui=cont.get("image"), force=force)
    wb.load_workflows()
    prompt, wf = wb.build_first_frame(
        shot, character_desc=", ".join(char_descs),
        scene_desc=scene_desc, multi_char_prompt=multi_char_prompt)

    if not wf:
        return _err(shot_id, "first_frame", "首帧工作流为空（缺少模板）")

    comfyui = cont.get("image")

    # ── LoRA 资源检查：验证工作流中的 LoRA 文件是否存在于 ComfyUI 服务器 ──
    from engines.workflow import find_lora_nodes
    from infra.asset_tracker import AssetTracker
    from urllib.parse import urlparse

    tracker = AssetTracker(cfg.project_dir)
    image_server_url = comfyui.url
    lora_nodes = find_lora_nodes(wf)

    for node_id, lora_name in lora_nodes:
        if tracker.is_lora_tracked(image_server_url, lora_name):
            continue  # 已确认存在

        # 检测服务器是否为本机
        parsed = urlparse(image_server_url)
        is_local = parsed.hostname in ("localhost", "127.0.0.1", "::1")

        found = False
        if is_local:
            # 本机 ComfyUI：尝试检查 models/loras 目录
            loras_dir_candidates = [
                Path.home() / "ComfyUI" / "models" / "loras",
                Path("/opt/ComfyUI/models/loras"),
            ]
            for loras_dir in loras_dir_candidates:
                if (loras_dir / lora_name).exists():
                    tracker.mark_lora_tracked(image_server_url, lora_name)
                    logger.debug(f"LoRA {lora_name} 在本地 ComfyUI 已确认存在 ({loras_dir})")
                    found = True
                    break

        if not found:
            logger.warning(
                f"LoRA '{lora_name}' 未确认存在于服务器 {image_server_url}，"
                f"工作流可能执行失败。请将文件放入 ComfyUI 的 models/loras/ 目录"
            )

    # ── 上传参考图 ──
    from engines.workflow import find_character_load_image_nodes as _find_char_nodes
    from infra.asset_tracker import comfyui_asset_name
    _char_node_set = set(_find_char_nodes(wf))
    for node_id, file_path in wb.build_upload_map(shot, wf).items():
        if Path(file_path).exists():
            try:
                # 角色参考图：用 project_dir+char_id 生成唯一文件名 + AssetTracker 跟踪
                if node_id in _char_node_set and "/assets/characters/" in file_path:
                    parts = Path(file_path).parts
                    char_idx = parts.index("characters") + 1
                    cid = parts[char_idx] if char_idx < len(parts) else "unknown"
                    remote_name = comfyui_asset_name(cfg.project_dir, cid, Path(file_path).name)
                else:
                    remote_name = Path(file_path).name
                comfyui.upload_image(file_path, filename=remote_name)
                if node_id in wf and wf[node_id].get("class_type") in ("LoadImage", "LoadImageFromPath", "ImageLoad"):
                    wf[node_id]["inputs"]["image"] = remote_name
            except Exception as e:
                logger.warning(f"参考图上传失败 [{node_id}]: {e}")

    try:
        files = comfyui.generate(wf, str(out_dir))
    except Exception as e:
        return _err(shot_id, "first_frame", f"ComfyUI 首帧生成失败: {e}")

    if not files:
        return _err(shot_id, "first_frame", "ComfyUI 未返回任何图片")
    frame_path = str(out_dir / "frame.png")
    os.replace(files[0], frame_path)
    return _done(shot_id, "first_frame", frame_path, prompt=prompt.get("positive", ""))


def video_core(shot_id: str, cfg, cont, out_dir: Path, *, shot: dict | None = None, force: bool = False) -> dict:
    """视频生成核心逻辑 — 从首帧生成视频

    Args:
        shot_id: 镜头 ID
        cfg: Config 对象
        cont: DI 容器
        out_dir: 输出目录
        shot: 镜头数据（含 duration），用于动态计算视频帧数
        force: True 时覆盖已有文件，False 时跳过

    Returns:
        {"status": "done"/"skipped"/"error", ...}
    """
    frame_path = out_dir / "frame.png"
    if not frame_path.exists():
        return _skip(shot_id, "video", "首帧不存在，请先执行 Step 2")

    # 已有文件且非强制模式 → 跳过
    video_path = out_dir / "video.mp4"
    if not force and video_path.exists():
        return _skip(shot_id, "video", "视频已存在")

    from engines.workflow_builder import WorkflowBuilder
    from engines.workflow import find_load_image_nodes
    wb = WorkflowBuilder(cfg.data, cfg.get("models", {}), cfg.project_dir, comfyui=cont.get("image"))
    wb.load_workflows()
    video_wf = wb.build_video(str(frame_path), shot=shot)
    if not video_wf:
        return _err(shot_id, "video", "视频工作流为空（缺少模板）")

    # 智能判断是否需要上传首帧图到视频 ComfyUI 服务器
    # 检测资源是否真的存在（而非仅凭 URL），确保文件不跨项目/跨集覆盖
    image_backend = cont.get("image")
    video_backend = cont.get("video")
    load_nodes = find_load_image_nodes(video_wf)

    # 构建全局唯一服务器文件名: {项目}_{集}_{镜头}_frame.png
    # ComfyUI LoadImage 节点不接受非 ASCII 文件名，需做安全化处理
    project_name = os.path.basename(cfg.project_dir) or "project"
    if re.search(r'[^\x00-\x7f]', project_name):
        # 含非 ASCII 字符（如中文）：用原名的短 hash 替代，确保唯一且纯 ASCII
        ascii_name = "proj_" + hashlib.md5(project_name.encode("utf-8")).hexdigest()[:8]
        logger.debug(f"项目名含非 ASCII 字符 '{project_name}' → 服务端文件名使用 '{ascii_name}'")
    else:
        ascii_name = project_name
    # 尝试从路径中提取集号: .../output/ep01/001/ → ep01
    ep_tag = ""
    parent = out_dir.parent.name
    if parent.startswith("ep") and parent[2:].isdigit():
        ep_tag = f"_{parent}"
    server_filename = f"{ascii_name}{ep_tag}_{shot_id}_frame.png"

    if load_nodes:
        video_comfyui = video_backend._get_comfyui() if hasattr(video_backend, "_get_comfyui") else video_backend
        video_server_url = getattr(video_comfyui, "url", "").rstrip("/")

        # 1) 判断是否需要上传：tracker 记录了 + 服务端确实存在 → 跳过
        #    避免"删除项目→重建同名项目"时，旧图残留在服务器导致跳过上传
        from infra.asset_tracker import AssetTracker
        tracker = AssetTracker(cfg.project_dir)
        already_tracked = tracker.is_image_tracked(video_server_url, server_filename)

        need_upload = True
        if already_tracked:
            try:
                if video_comfyui.check_image_exists(server_filename, asset_type="input"):
                    logger.debug(f"首帧图 {server_filename} 已在视频服务器 {video_server_url}，跳过上传")
                    need_upload = False
                else:
                    # 服务器文件丢失（如被清理），清理 tracker 记录重新上传
                    tracker.untrack_image(video_server_url, server_filename)
            except Exception as e:
                logger.debug(f"检查首帧图存在性失败: {e}，回退上传")

        # 2) 不存在则上传（使用 server_filename 作为服务端文件名，与工作流引用一致）
        if need_upload:
            try:
                video_comfyui.upload_image(str(frame_path), filename=server_filename)
                tracker.mark_image_tracked(video_server_url, server_filename)
                logger.debug(f"首帧图 {server_filename} 已上传到视频服务器")
            except Exception as e:
                logger.warning(f"首帧图上传失败: {e}")

        # 3) 始终更新工作流节点引用为服务器文件名（即使跳过上传也要设置）
        if load_nodes[0] in video_wf:
            video_wf[load_nodes[0]]["inputs"]["image"] = server_filename


    try:
        files = video_backend.generate(video_wf, str(out_dir))
    except Exception as e:
        return _err(shot_id, "video", f"视频生成失败: {e}")

    if not files:
        return _err(shot_id, "video", "ComfyUI 未返回任何视频")
    video_path = str(out_dir / "video.mp4")
    os.replace(files[0], video_path)
    return _done(shot_id, "video", video_path)


def lipsync_core(shot_id: str, cont, out_dir: Path, *, force: bool = False) -> dict:
    """口型同步核心逻辑 — 视频 + 音频 → 口型同步视频

    Args:
        shot_id: 镜头 ID
        cont: DI 容器
        out_dir: 输出目录
        force: True 时覆盖已有文件，False 时跳过

    Returns:
        {"status": "done"/"skipped"/"error", ...}
    """
    video_path, audio_path = out_dir / "video.mp4", out_dir / "audio.wav"
    if not video_path.exists():
        return _skip(shot_id, "lipsync", "视频不存在，请先执行 Step 3")
    if not audio_path.exists():
        return _skip(shot_id, "lipsync", "音频不存在，请先执行 Step 1")

    # 已有文件且非强制模式 → 跳过
    synced_path = out_dir / "synced.mp4"
    if not force and synced_path.exists():
        return _skip(shot_id, "lipsync", "口型同步视频已存在")

    synced_path = str(out_dir / "synced.mp4")
    try:
        cont.get("lipsync").sync(str(video_path), str(audio_path), synced_path)
    except Exception as e:
        return _err(shot_id, "lipsync", f"口型同步失败: {e}")
    return _done(shot_id, "lipsync", synced_path)


# ── Celery 任务包装（_prepare 防重复 + 核心逻辑）──

def _run_tts(config_path: str, episode: int, shot_id: str, *, force: bool = False) -> dict:
    cfg, cont, shot, err = _prepare(config_path, episode, shot_id, "tts", "tts", force=force)
    if err:
        return err
    return tts_core(shot_id, shot, cfg, cont, _shot_dir(config_path, episode, shot_id), force=force)


def _run_first_frame(config_path: str, episode: int, shot_id: str, *, force: bool = False) -> dict:
    cfg, cont, shot, err = _prepare(config_path, episode, shot_id, "first_frame", "comfyui", force=force)
    if err:
        return err
    return first_frame_core(shot_id, shot, cfg, cont, _shot_dir(config_path, episode, shot_id), force=force)


def _run_video(config_path: str, episode: int, shot_id: str, *, force: bool = False) -> dict:
    cfg, cont, shot, err = _prepare(config_path, episode, shot_id, "video", "comfyui", need_shot=True, force=force)
    if err:
        return err
    return video_core(shot_id, cfg, cont, _shot_dir(config_path, episode, shot_id), shot=shot, force=force)


def _run_lipsync(config_path: str, episode: int, shot_id: str, *, force: bool = False) -> dict:
    cfg, cont, _, err = _prepare(config_path, episode, shot_id, "lipsync", "lipsync", need_shot=False, force=force)
    if err:
        return err
    return lipsync_core(shot_id, cont, _shot_dir(config_path, episode, shot_id), force=force)


# ══════════════════════════════════════════════════════════
#  Celery 任务包装
# ══════════════════════════════════════════════════════════

def _step_task(self, step: str, fn, config_path: str, episode: int, shot_id: str, *, force: bool = False):
    """通用 Celery 步骤任务包装"""
    self.update_state(state="PROGRESS", meta={"step": step, "shot_id": shot_id, "progress": 10, "message": f"[{shot_id}] {step} 开始..."})
    try:
        result = fn(config_path, episode, shot_id, force=force)
    except SoftTimeLimitException:
        logger.warning(f"[{shot_id}] {step} 超时（soft_time_limit）")
        _db_record_step(config_path, episode, shot_id, step, {"status": "error", "reason": "执行超时"})
        return {"shot_id": shot_id, "step": step, "status": "error", "reason": "执行超时"}
    except Exception as e:
        logger.error(f"[{shot_id}] {step} 异常: {e}")
        return {"shot_id": shot_id, "step": step, "status": "error", "reason": str(e)}
    if result.get("status") == "done":
        self.update_state(state="PROGRESS", meta={"step": step, "shot_id": shot_id, "progress": 100, "message": f"[{shot_id}] {step} 完成"})
    elif result.get("status") == "error":
        self.update_state(state="PROGRESS", meta={"step": step, "shot_id": shot_id, "progress": 100, "message": f"[{shot_id}] {step} 失败: {result.get('reason', '')}"})
    return result


@app.task(bind=True, name="pipeline.step.tts", soft_time_limit=120)
def step_tts(self, config_path, episode, shot_id, force=False): return _step_task(self, "tts", _run_tts, config_path, episode, shot_id, force=force)

@app.task(bind=True, name="pipeline.step.first_frame", soft_time_limit=300)
def step_first_frame(self, config_path, episode, shot_id, force=False): return _step_task(self, "first_frame", _run_first_frame, config_path, episode, shot_id, force=force)

@app.task(bind=True, name="pipeline.step.video", soft_time_limit=600)
def step_video(self, config_path, episode, shot_id, force=False): return _step_task(self, "video", _run_video, config_path, episode, shot_id, force=force)

@app.task(bind=True, name="pipeline.step.lipsync", soft_time_limit=300)
def step_lipsync(self, config_path, episode, shot_id, force=False): return _step_task(self, "lipsync", _run_lipsync, config_path, episode, shot_id, force=force)


# ══════════════════════════════════════════════════════════
#  编排器
# ══════════════════════════════════════════════════════════

@app.task(bind=True, name="pipeline.shot", soft_time_limit=1800)
def shot_task(self, config_path: str, episode: int, shot_data: dict, force: bool = False) -> dict:
    shot_id = shot_data.get("shot_id", "")
    if not shot_id:
        return {"shot_id": "", "status": "error", "reason": "镜头数据缺少 shot_id"}
    steps = [("tts", _run_tts), ("first_frame", _run_first_frame), ("video", _run_video), ("lipsync", _run_lipsync)]
    results = {}
    for i, (name, fn) in enumerate(steps):
        self.update_state(state="PROGRESS", meta={"step": name, "shot_id": shot_id, "progress": int((i + 1) / len(steps) * 100), "message": f"[{shot_id}] {name} ({i+1}/{len(steps)})"})
        try:
            t0 = time.time()
            result = fn(config_path, episode, shot_id, force=force)
            result["elapsed"] = round(time.time() - t0, 2)
            results[name] = result
            _db_record_step(config_path, episode, shot_id, name, result)
            log = logger.info if result.get("status") == "done" else logger.warning if result.get("status") == "error" else logger.info
            log(f"[{shot_id}] {name}: {result.get('status')} — {result.get('reason', '')}")
        except Exception as e:
            logger.error(f"[{shot_id}] {name}: 异常 — {e}")
            results[name] = {"status": "error", "reason": str(e)}
            _db_record_step(config_path, episode, shot_id, name, {"status": "error", "reason": str(e)})

    return {"shot_id": shot_id,
            "done": [k for k, v in results.items() if v.get("status") == "done"],
            "skipped": [k for k, v in results.items() if v.get("status") == "skipped"],
            "errors": [k for k, v in results.items() if v.get("status") == "error"],
            "details": results}


# ══════════════════════════════════════════════════════════
#  集级任务
# ══════════════════════════════════════════════════════════

def _iterate_shots(self, config_path: str, episode: int, shots: list[dict], progress_base: int = 0, progress_range: int = 100, *, force: bool = False):
    """逐镜头执行 shot_task，返回结果列表"""
    total = len(shots)
    results = []
    for i, shot in enumerate(shots):
        shot_id = shot.get("shot_id", f"{i+1:03d}")
        self.update_state(state="PROGRESS", meta={"step": "shot", "shot_id": shot_id,
            "progress": int(progress_base + i / total * progress_range), "current": i + 1, "total": total,
            "message": f"[{i+1}/{total}] 镜头 {shot_id}"})
        try:
            results.append(shot_task.apply(args=[config_path, episode, shot], kwargs={"force": force}).get(timeout=1800))
        except Exception as e:
            results.append({"shot_id": shot_id, "error": str(e)})
    return results


@app.task(bind=True, name="pipeline.preview", soft_time_limit=1800)
def preview_task(self, config_path: str, episode: int, preset: str = "draft", force: bool = False) -> dict:
    shots = _load_episode_shots(config_path, episode)
    if not shots:
        return {"status": "empty", "message": f"第{episode}集没有镜头"}
    # 根据 preset 缩放生成参数，写入临时配置文件
    effective_cfg = _apply_preset(config_path, preset)
    try:
        return {"status": "done", "episode": episode, "preset": preset,
                "shots": _iterate_shots(self, effective_cfg, episode, shots, force=force)}
    finally:
        # 清理临时配置文件
        if effective_cfg != config_path:
            try:
                os.unlink(effective_cfg)
            except OSError:
                pass


def _apply_preset(config_path: str, preset: str) -> str:
    """根据 preset 缩放生成参数，返回（可能新建的）配置文件路径"""
    if preset == "draft":
        return config_path  # draft 不修改，使用默认参数
    from infra.config import Config, save_config, load_config
    import tempfile
    cfg = Config(config_path)
    gen = cfg.get("generation", {})
    base_steps = gen.get("image_steps", 20)
    base_res = gen.get("resolution", [512, 512])
    if preset == "high":
        overrides = {
            "image_steps": int(base_steps * 1.4),
            "resolution": [min(1920, int(base_res[0] * 1.5)), min(1080, int(base_res[1] * 1.5))],
        }
    else:  # standard
        return config_path
    # 写入临时配置文件（继承原配置 + 覆盖 generation 段）
    existing = load_config(config_path)
    existing.setdefault("generation", {}).update(overrides)
    fd, tmp_path = tempfile.mkstemp(suffix=".yaml", dir=str(Path(config_path).parent))
    os.close(fd)
    save_config(tmp_path, existing)
    return tmp_path


@app.task(bind=True, name="pipeline.produce", soft_time_limit=7200)
def produce_task(self, config_path: str, episode: int, vertical: bool = False, force: bool = False) -> dict:
    shots = _load_episode_shots(config_path, episode)
    if not shots:
        return {"status": "empty", "message": f"第{episode}集没有镜头"}
    try:
        self.update_state(state="PROGRESS", meta={"step": "subtitle", "progress": 2, "message": "生成字幕..."})
        _run_subtitle(config_path, episode)
    except Exception as e:
        logger.warning(f"字幕失败: {e}")
    results = _iterate_shots(self, config_path, episode, shots, progress_base=5, progress_range=80, force=force)
    self.update_state(state="PROGRESS", meta={"step": "post", "progress": 90, "message": "后期合成..."})
    try:
        _run_post(config_path, episode, vertical)
    except Exception as e:
        logger.error(f"后期失败: {e}")
    return {"status": "done", "episode": episode, "shots": results}


@app.task(bind=True, name="pipeline.post", soft_time_limit=1200)
def post_task(self, config_path: str, episode: int, vertical: bool = False) -> dict:
    _ensure_path()
    self.update_state(state="PROGRESS", meta={"step": "post", "progress": 10})
    try:
        _run_post(config_path, episode, vertical)
    except Exception as e:
        logger.error(f"后期合成失败: {e}")
        return {"status": "error", "episode": episode, "reason": str(e)}
    return {"status": "done", "episode": episode, "vertical": vertical}


@app.task(bind=True, name="pipeline.portraits", soft_time_limit=1800)
def portraits_task(self, config_path: str, force: bool = False) -> dict:
    _ensure_path()
    self.update_state(state="PROGRESS", meta={"step": "portraits", "progress": 10})
    try:
        from pipeline.portraits import run_portraits
        run_portraits(config_path, force=force)
    except Exception as e:
        logger.error(f"定妆照生成失败: {e}")
        return {"status": "error", "reason": str(e)}
    return {"status": "done"}


@app.task(bind=True, name="pipeline.scene_images", soft_time_limit=1800)
def scene_images_task(self, config_path: str, force: bool = False) -> dict:
    """为所有场景批量生成参考图"""
    _ensure_path()
    update = self.update_state  # 局部变量，避免闭包持有 self

    update(state="PROGRESS", meta={"step": "scene_images", "progress": 10, "message": "加载场景..."})
    try:
        from pipeline.scene_images import run_scene_images

        def on_progress(current, total, msg):
            update(state="PROGRESS", meta={
                "step": "scene_images",
                "progress": int(10 + current / max(total, 1) * 80),
                "message": f"[{current}/{total}] {msg}",
                "current": current, "total": total})

        return run_scene_images(config_path, force=force, progress_cb=on_progress)
    except Exception as e:
        logger.error(f"场景图批量生成失败: {e}")
        return {"status": "error", "reason": str(e)}


# ══════════════════════════════════════════════════════════
#  单资产生成任务（异步，复用已有工具函数）
# ══════════════════════════════════════════════════════════

@app.task(bind=True, name="pipeline.portrait_single", soft_time_limit=600)
def portrait_single_task(self, config_path: str, char_id: str) -> dict:
    """为单个角色 AI 生成定妆照 + 各服装参考图（异步）"""
    _ensure_path()

    self.update_state(state="PROGRESS", meta={"step": "portrait", "progress": 10, "message": f"生成 {char_id} 定妆照..."})

    # 检查角色是否存在
    project_dir = _cfg_dir(config_path)
    char_yaml_path = project_dir / "config" / "characters" / f"{char_id}.yaml"
    if not char_yaml_path.exists():
        return {"status": "error", "reason": f"角色 {char_id} 不存在"}

    try:
        from pipeline.portraits import run_portraits
        run_portraits(config_path, force=True, char_ids=[char_id], write_db=True)
    except Exception as e:
        return {"status": "error", "reason": f"定妆照生成失败: {e}"}

    return {"status": "done", "char_id": char_id}


@app.task(bind=True, name="pipeline.outfit_single", soft_time_limit=300)
def outfit_single_task(self, config_path: str, char_id: str, outfit_key: str) -> dict:
    """为单个角色的指定服装生成参考图（异步）"""
    _ensure_path()
    from engines.workflow_builder import WorkflowBuilder
    from engines.prompt import translate_to_english

    self.update_state(state="PROGRESS", meta={"step": "outfit", "progress": 10, "message": f"生成 {char_id}/{outfit_key} 服装图..."})

    cfg, cont = _init_ctx(config_path)
    project_dir = _cfg_dir(config_path)

    char_yaml_path = project_dir / "config" / "characters" / f"{char_id}.yaml"
    if not char_yaml_path.exists():
        return {"status": "error", "reason": f"角色 {char_id} 不存在"}

    with open(char_yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    char = data.get("character", {})
    appearance = char.get("appearance", char_id)
    outfits = char.get("outfits", {})

    if not isinstance(outfits, dict) or outfit_key not in outfits:
        available = list(outfits.keys()) if isinstance(outfits, dict) else []
        return {"status": "error", "reason": f"角色 {char_id} 没有名为 '{outfit_key}' 的服装，可用: {available}"}

    outfit_val = outfits[outfit_key]
    outfit_desc = outfit_val.get("description", "")
    if not outfit_desc:
        return {"status": "error", "reason": f"角色 {char_id} 的服装 '{outfit_key}' 描述为空"}

    try:
        comfyui = cont.get("image")
    except Exception as e:
        return {"status": "error", "reason": f"ComfyUI 不可用: {e}"}

    outfit_dir = project_dir / "assets" / "characters" / char_id / outfit_key
    outfit_dir.mkdir(parents=True, exist_ok=True)
    # 记录旧图，生成成功后再删除（避免生成失败导致无图）
    old_outfit_imgs = list(outfit_dir.glob("*.png")) + list(outfit_dir.glob("*.jpg"))

    full_desc = f"{appearance}, wearing {outfit_desc}"
    if any(ord(c) > 127 for c in full_desc):
        full_desc = translate_to_english(full_desc, llm=None)

    models = cfg.get("models", {})
    wb = WorkflowBuilder(cfg.data, models, str(project_dir), comfyui=comfyui)
    wb.load_workflows()

    # 确定性 seed + cover 参考图（保持角色面部一致性）
    from engines.portrait import _outfit_seed
    generation = char.get("portrait_generation", 0)
    outfit_keys = list(outfits.keys())
    outfit_idx = outfit_keys.index(outfit_key) if outfit_key in outfit_keys else 0
    outfit_seed = _outfit_seed(char_id, generation, outfit_idx)

    fake_shot = {"characters": char_id, "emotion": "neutral",
                 "shot_type": "全身", "camera": "固定"}
    _, wf = wb.build_first_frame(fake_shot, character_desc=full_desc, seed=outfit_seed)
    if not wf:
        return {"status": "error", "reason": "首帧工作流为空（缺少模板）"}

    # 注入 cover 做 IP-Adapter 参考
    cover_ref = project_dir / "assets" / "characters" / char_id / "cover.png"
    if cover_ref.exists():
        from engines.workflow import find_character_load_image_nodes
        from infra.asset_tracker import comfyui_asset_name, AssetTracker
        char_nodes = find_character_load_image_nodes(wf)
        if char_nodes:
            remote_name = comfyui_asset_name(str(project_dir), char_id, os.path.basename(str(cover_ref)))
            wf[char_nodes[0]]["inputs"]["image"] = remote_name
            try:
                tracker = AssetTracker(str(project_dir))
                tracker.upload_if_needed(comfyui, str(cover_ref), remote_name, comfyui.url)
            except Exception as e:
                logger.warning(f"参考图上传失败: {e}")

    self.update_state(state="PROGRESS", meta={"step": "outfit", "progress": 50, "message": "ComfyUI 生成中..."})
    try:
        files = comfyui.generate(wf, str(outfit_dir))
    except Exception as e:
        return {"status": "error", "reason": f"ComfyUI 生成失败: {e}"}
    if not files:
        return {"status": "error", "reason": "ComfyUI 未返回任何图片"}

    # 生成成功后删除旧图
    for old_img in old_outfit_imgs:
        try:
            old_img.unlink()
        except OSError:
            pass

    # 重命名为 cover.png
    cover_path = outfit_dir / "cover.png"
    os.replace(files[0], str(cover_path))
    img_url = f"/api/assets/characters/{char_id}/{outfit_key}/cover.png"

    # 更新角色 YAML 中该 outfit 的 reference_images
    try:
        with open(char_yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        char = data.get("character", {})
        outfits_data = char.get("outfits", {})
        if isinstance(outfits_data, dict) and outfit_key in outfits_data:
            outfit_val = outfits_data[outfit_key]
            outfit_val.setdefault("reference_images", [])
            prefix = f"/api/assets/characters/{char_id}/{outfit_key}/cover"
            outfit_val["reference_images"] = [u for u in outfit_val["reference_images"] if not u.startswith(prefix)]
            outfit_val["reference_images"].append(img_url)
        char["outfits"] = outfits_data
        data["character"] = char
        from infra.config import save_yaml
        save_yaml(char_yaml_path, data)
    except Exception as e:
        logger.debug(f"更新 outfit reference_images 跳过: {e}")

    return {"status": "done", "url": img_url, "char_id": char_id, "outfit": outfit_key}


@app.task(bind=True, name="pipeline.outfits_batch", soft_time_limit=600)
def outfits_batch_task(self, config_path: str, char_id: str) -> dict:
    """为单个角色的所有服装批量生成参考图（异步）"""
    _ensure_path()

    self.update_state(state="PROGRESS", meta={"step": "outfits", "progress": 5, "message": f"加载角色 {char_id}..."})

    project_dir = _cfg_dir(config_path)
    char_yaml_path = project_dir / "config" / "characters" / f"{char_id}.yaml"
    if not char_yaml_path.exists():
        return {"status": "error", "reason": f"角色 {char_id} 不存在"}

    with open(char_yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    char = data.get("character", {})
    outfits = char.get("outfits", {})

    if not isinstance(outfits, dict) or not outfits:
        return {"status": "error", "reason": f"角色 {char_id} 没有定义任何服装"}

    total = len(outfits)
    results = []
    errors = []
    for i, key in enumerate(outfits):
        self.update_state(state="PROGRESS", meta={
            "step": "outfits", "progress": int(10 + i / total * 80),
            "message": f"[{i+1}/{total}] 生成 {key}...", "current": i + 1, "total": total})
        try:
            result = outfit_single_task.apply(args=[config_path, char_id, key]).get(timeout=300)
            if result.get("status") == "done":
                results.append(result)
            else:
                errors.append({"outfit": key, "error": result.get("reason", "未知错误")})
        except Exception as e:
            errors.append({"outfit": key, "error": str(e)})

    return {"status": "done", "char_id": char_id,
            "generated": results, "errors": errors,
            "total": total, "success": len(results), "failed": len(errors)}


@app.task(bind=True, name="pipeline.scene_image_single", soft_time_limit=300)
def scene_image_single_task(self, config_path: str, scene_id: str) -> dict:
    """为单个场景 AI 生成参考图（异步）"""
    _ensure_path()

    update = self.update_state  # 局部变量，避免闭包持有 self

    update(state="PROGRESS", meta={"step": "scene_image", "progress": 10, "message": f"生成场景 {scene_id} 参考图..."})

    def on_progress(current, total, msg):
        update(state="PROGRESS", meta={
            "step": "scene_image", "progress": int(10 + current / max(total, 1) * 80),
            "message": f"生成场景 {msg}..."})

    try:
        from pipeline.scene_images import run_scene_images
        result = run_scene_images(config_path, force=True, scene_ids=[scene_id], progress_cb=on_progress)
        if result.get("status") == "error":
            return result
        return {"status": "done", "scene_id": scene_id, **result}
    except Exception as e:
        return {"status": "error", "reason": f"场景图生成失败: {e}"}


# ══════════════════════════════════════════════════════════
#  独立工具任务
# ══════════════════════════════════════════════════════════

def _run_subtitle(config_path: str, episode: int) -> dict:
    cfg, _ = _init_ctx(config_path)
    from post.subtitle import generate_srt
    sb = _cfg_dir(config_path, "storyboard", "episodes.csv")
    if not sb.exists():
        return {"error": "分镜表不存在"}
    with open(sb, encoding="utf-8") as f:
        shots = [dict(r) for r in csv.DictReader(f) if _safe_int(r.get("episode", 0)) == episode]
    if not shots:
        return {"error": f"第{episode}集没有镜头"}
    out_dir = _cfg_dir(config_path, "output", f"e{episode:02d}")
    out_dir.mkdir(parents=True, exist_ok=True)
    srt = str(out_dir / f"episode_{episode:02d}.srt")
    generate_srt(shots, srt, transition_duration=cfg.get("post_production.transition_duration", 0.5))
    return {"path": srt, "count": len(shots)}


def _run_post(config_path: str, episode: int, vertical: bool = False) -> None:
    _ensure_path()
    from post.production import run_post
    run_post(config_path, episode, vertical)


@app.task(bind=True, name="pipeline.tts_single", soft_time_limit=120)
def tts_single_task(self, config_path: str, text: str, voice_config: dict | None = None,
                    emotion: str = "neutral", language: str = "zh"):
    cfg, cont = _init_ctx(config_path)
    self.update_state(state="PROGRESS", meta={"step": "tts", "progress": 20, "message": "TTS..."})
    # 保存到项目目录下，使前端可通过 /api/files 访问
    preview_dir = Path(cfg.project_dir) / "output" / "tts_preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    tag = hashlib.md5(f"{text}{time.time()}".encode()).hexdigest()[:8]
    output = str(preview_dir / f"preview_{tag}.wav")
    try:
        result = cont.get("tts").synthesize(text, output, voice_config=voice_config or {}, emotion=emotion, language=language)
        # 返回相对于项目目录的路径
        rel_path = str(Path(result).relative_to(cfg.project_dir))
        return {"path": rel_path, "text": text}
    except Exception as e:
        return {"status": "error", "reason": f"TTS 合成失败: {e}", "text": text}


@app.task(bind=True, name="pipeline.music", soft_time_limit=120)
def music_task(self, config_path: str, duration: float, mood: str, output: str) -> dict:
    cfg, _ = _init_ctx(config_path)
    from post.music import MusicGenerator
    gen = MusicGenerator(backend=cfg.get("models", {}).get("music_backend", "template"), config=cfg.data)
    try:
        result = gen.generate(duration, output, mood=mood)
    except Exception as e:
        return {"status": "error", "reason": f"配乐生成失败: {e}", "mood": mood, "duration": duration}
    return {"path": result, "mood": mood, "duration": duration}


@app.task(bind=True, name="pipeline.subtitle", soft_time_limit=60)
def subtitle_task(self, config_path: str, episode: int):
    return _run_subtitle(config_path, episode)


# ══════════════════════════════════════════════════════════
#  AI 生成任务（异步，避免网关超时）
# ══════════════════════════════════════════════════════════

@app.task(bind=True, name="pipeline.ai.storyboard", soft_time_limit=600)
def ai_storyboard_task(self, config_path: str, episode: int, outline: str,
                       duration: int = 90, append: bool = False):
    """AI 生成分镜表 + 自动补全角色/场景（面向新用户）"""
    from engines.llm_generator import generate_storyboard, generate_characters, generate_scenes
    from engines.storyboard import save_storyboard

    self.update_state(state="PROGRESS", meta={"step": "ai_storyboard", "progress": 10, "message": "正在初始化 LLM..."})

    cfg, cont = _init_ctx(config_path)
    try:
        llm = cont.get("llm")
    except Exception as e:
        return {"status": "error", "reason": f"LLM 初始化失败: {e}"}

    project_dir = _cfg_dir(config_path)

    # ── 1. 生成分镜（不传已有角色/场景，新用户没有） ──
    self.update_state(state="PROGRESS", meta={"step": "ai_storyboard", "progress": 30, "message": "AI 正在生成分镜..."})

    try:
        shots = generate_storyboard(llm, outline, [], [], episode, duration)
    except Exception as e:
        return {"status": "error", "reason": f"LLM 生成失败: {e}"}

    if not shots:
        return {"status": "error", "reason": "LLM 未能生成有效分镜"}

    # ── 2. 提取分镜中引用的所有角色/场景 ID ──
    char_ids = set()
    scene_ids = set()
    for shot in shots:
        for cid in (shot.get("characters") or "").split("+"):
            cid = cid.strip()
            if cid:
                char_ids.add(cid)
        sid = (shot.get("scene") or "").strip()
        if sid:
            scene_ids.add(sid)

    generated_chars = []
    generated_scenes = []
    id_remap = {}

    if char_ids or scene_ids:
        self.update_state(state="PROGRESS", meta={
            "step": "ai_storyboard", "progress": 60,
            "message": f"正在生成 {len(char_ids)} 个角色、{len(scene_ids)} 个场景..."})

    # ── 3. 批量生成角色 ──
    if char_ids:
        char_dir = project_dir / "config" / "characters"
        char_dir.mkdir(parents=True, exist_ok=True)

        char_descriptions = []
        sorted_ids = sorted(char_ids)
        for cid in sorted_ids:
            char_shots = [s for s in shots if cid in (s.get("characters") or "").split("+")]
            actions = [s.get("action", "") for s in char_shots[:5]]
            dialogues = [s.get("dialogue", "") for s in char_shots[:5] if s.get("dialogue") and s.get("dialogue") != "......"]
            desc_parts = [
                f"根据以下信息生成角色「{cid}」的配置。",
                f"角色ID: {cid}（必须原样填入 id 字段，不可修改）",
                f"剧情大纲: {outline}",
                f"该角色在分镜中的表现:",
            ]
            if actions:
                for idx, a in enumerate(actions, 1):
                    desc_parts.append(f"  镜头{idx}: {a}")
            if dialogues:
                desc_parts.append(f"台词: {' / '.join(dialogues)}")
            desc_parts.append(f"\n【重要】此角色的 id 必须为「{cid}」，且 name 必须是与其他角色不同的独立名字（根据角色背景可以是中文或英文），不能与其他角色重名。")
            char_descriptions.append("\n".join(desc_parts))

        try:
            new_chars = generate_characters(llm, char_descriptions, expected_ids=sorted_ids)

            # ── 合并同名角色（LLM 可能为同一角色使用不同 ID，如 insurance_agent 和 linxia）──
            name_to_first: dict[str, str] = {}  # char_name → first old_id
            for i, char in enumerate(new_chars):
                if char is None:
                    continue
                old_id = sorted_ids[i]
                char_name = char.get("name", "").strip()
                if not char_name:
                    char_name = old_id
                if char_name in name_to_first:
                    # 同名角色已存在，合并：将当前 old_id 指向第一个角色的 new_id
                    first_old_id = name_to_first[char_name]
                    logger.warning(f"  ⚠ 角色名重复: '{char_name}'（{old_id} 与 {first_old_id}），合并为同一角色")
                    # id_remap 会在后续步骤中将 old_id 映射到 first 的 new_id
                    # 这里先标记，等第一个角色生成 new_id 后再设置
                    continue
                name_to_first[char_name] = old_id

            for i, char in enumerate(new_chars):
                if char is None:
                    logger.warning(f"  ⚠ 角色 {sorted_ids[i]} 生成失败，跳过")
                    continue
                old_id = sorted_ids[i]
                char_name = char.get("name", "").strip()
                if not char_name:
                    char_name = old_id

                # 如果这个 old_id 不是 name_to_first 中记录的第一个，跳过（已被合并）
                if name_to_first.get(char_name) != old_id:
                    # 将合并的 old_id 指向第一个角色的 new_id（第一个角色此时已处理）
                    first_old_id = name_to_first[char_name]
                    if first_old_id in id_remap:
                        id_remap[old_id] = id_remap[first_old_id]
                        logger.info(f"  🔗 合并: {old_id} → {id_remap[first_old_id]}（同名 '{char_name}'）")
                    continue

                new_id = _unique_hash_id("ch", char_name, id_remap)
                char["id"] = new_id
                char["name"] = char_name
                id_remap[old_id] = new_id

                path = char_dir / f"{new_id}.yaml"
                from infra.config import save_yaml
                save_yaml(path, {"character": char})
                try:
                    from infra.database.characters import upsert as db_up
                    from infra.database.pool import get_pool
                    db_up(get_pool(), new_id, char)
                except Exception as e:
                    logger.warning(f"DB 写入跳过: {e}")
                generated_chars.append(new_id)
                logger.info(f"  ✅ 角色: {char_name} ({old_id} → {new_id})")
        except Exception as e:
            logger.warning(f"  ⚠ 角色生成失败: {e}")

    # ── 4. 批量生成场景 ──
    if scene_ids:
        scene_dir = project_dir / "config" / "scenes"
        scene_dir.mkdir(parents=True, exist_ok=True)

        scene_descriptions = []
        for sid in sorted(scene_ids):
            scene_shots = [s for s in shots if (s.get("scene") or "").strip() == sid]
            actions = [s.get("action", "") for s in scene_shots[:5]]
            desc_parts = [f"根据以下信息生成一个场景配置。", f"剧情大纲: {outline}", f"该场景在分镜中的画面:"]
            if actions:
                for idx, a in enumerate(actions, 1):
                    desc_parts.append(f"  镜头{idx}: {a}")
            scene_descriptions.append("\n".join(desc_parts))

        try:
            new_scenes_list = generate_scenes(llm, scene_descriptions)
            sorted_ids = sorted(scene_ids)

            # ── 合并同名场景 ──
            scene_name_to_first: dict[str, str] = {}
            for i, scene in enumerate(new_scenes_list):
                if scene is None:
                    continue
                old_id = sorted_ids[i]
                scene_name = scene.get("name", "").strip()
                if not scene_name:
                    scene_name = old_id
                if scene_name in scene_name_to_first:
                    first_old_id = scene_name_to_first[scene_name]
                    logger.warning(f"  ⚠ 场景名重复: '{scene_name}'（{old_id} 与 {first_old_id}），合并")
                    continue
                scene_name_to_first[scene_name] = old_id

            for i, scene in enumerate(new_scenes_list):
                if scene is None:
                    logger.warning(f"  ⚠ 场景 {sorted_ids[i]} 生成失败，跳过")
                    continue
                old_id = sorted_ids[i]
                scene_name = scene.get("name", "").strip()
                if not scene_name:
                    scene_name = old_id

                if scene_name_to_first.get(scene_name) != old_id:
                    first_old_id = scene_name_to_first[scene_name]
                    if first_old_id in id_remap:
                        id_remap[old_id] = id_remap[first_old_id]
                        logger.info(f"  🔗 合并: {old_id} → {id_remap[first_old_id]}（同名 '{scene_name}'）")
                    continue

                new_id = _unique_hash_id("sc", scene_name, id_remap)
                scene["id"] = new_id
                scene["name"] = scene_name
                id_remap[old_id] = new_id

                path = scene_dir / f"{new_id}.yaml"
                from infra.config import save_yaml
                save_yaml(path, {"scene": scene})
                try:
                    from infra.database.scenes import upsert as db_up
                    from infra.database.pool import get_pool
                    db_up(get_pool(), new_id, scene)
                except Exception as e:
                    logger.warning(f"DB 写入跳过: {e}")
                generated_scenes.append(new_id)
                logger.info(f"  ✅ 场景: {scene_name} ({old_id} → {new_id})")
        except Exception as e:
            logger.warning(f"  ⚠ 场景生成失败: {e}")

    # ── 5. 回写分镜：旧 ID → hash ID ──
    if id_remap:
        for shot in shots:
            chars = shot.get("characters", "")
            if chars:
                parts = [c.strip() for c in chars.split("+")]
                parts = [id_remap.get(c, c) for c in parts]
                shot["characters"] = "+".join(parts)
            scene = shot.get("scene", "")
            if scene in id_remap:
                shot["scene"] = id_remap[scene]

    # ── 6. 保存分镜 + DB 同步 ──
    self.update_state(state="PROGRESS", meta={"step": "ai_storyboard", "progress": 90, "message": "正在保存..."})

    sb_path = project_dir / "storyboard" / "episodes.csv"
    save_storyboard(sb_path, shots, episode, append)

    try:
        from infra.database.pool import get_pool
        from infra.database.shots import upsert as db_upsert_shot
        pool = get_pool()
        for shot in shots:
            sid = shot.get("shot_id", "")
            if sid:
                db_upsert_shot(pool, episode, sid, shot)
    except Exception as e:
        logger.warning(f"DB 写入跳过: {e}")

    total_sec = sum(int(s.get("duration", 4)) for s in shots)
    return {"status": "done", "episode": episode, "count": len(shots),
            "total_duration": total_sec, "shots": shots,
            "generated_characters": generated_chars,
            "generated_scenes": generated_scenes}


@app.task(bind=True, name="pipeline.ai.characters", soft_time_limit=300)
def ai_characters_task(self, config_path: str, descriptions: list[str]) -> dict:
    """AI 生成角色（异步）"""
    from engines.llm_generator import generate_characters

    self.update_state(state="PROGRESS", meta={"step": "ai_characters", "progress": 20, "message": "AI 正在生成角色..."})

    cfg, cont = _init_ctx(config_path)
    try:
        llm = cont.get("llm")
    except Exception as e:
        return {"status": "error", "reason": f"LLM 初始化失败: {e}"}

    try:
        chars = generate_characters(llm, descriptions)
    except Exception as e:
        return {"status": "error", "reason": f"生成失败: {e}"}

    if not chars or all(c is None for c in chars):
        return {"status": "error", "reason": "LLM 未能生成有效角色"}

    # 保存
    char_dir = _cfg_dir(config_path, "config", "characters")
    char_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for char in chars:
        if char is None:
            continue
        cid = char.get("id", "unknown")
        path = char_dir / f"{cid}.yaml"
        from infra.config import save_yaml
        save_yaml(path, {"character": char})
        try:
            from infra.database.characters import upsert as db_up
            from infra.database.pool import get_pool
            db_up(get_pool(), cid, char)
        except Exception as e:
            logger.warning(f"DB 写入跳过: {e}")
        saved.append(char)

    return {"status": "done", "count": len(saved), "characters": saved}


@app.task(bind=True, name="pipeline.ai.scenes", soft_time_limit=300)
def ai_scenes_task(self, config_path: str, descriptions: list[str]) -> dict:
    """AI 生成场景（异步）"""
    from engines.llm_generator import generate_scenes

    self.update_state(state="PROGRESS", meta={"step": "ai_scenes", "progress": 20, "message": "AI 正在生成场景..."})

    cfg, cont = _init_ctx(config_path)
    try:
        llm = cont.get("llm")
    except Exception as e:
        return {"status": "error", "reason": f"LLM 初始化失败: {e}"}

    try:
        scene_list = generate_scenes(llm, descriptions)
    except Exception as e:
        return {"status": "error", "reason": f"生成失败: {e}"}

    if not scene_list or all(s is None for s in scene_list):
        return {"status": "error", "reason": "LLM 未能生成有效场景"}

    scene_dir = _cfg_dir(config_path, "config", "scenes")
    scene_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for scene in scene_list:
        if scene is None:
            continue
        sid = scene.get("id", "unknown")
        path = scene_dir / f"{sid}.yaml"
        from infra.config import save_yaml
        save_yaml(path, {"scene": scene})
        try:
            from infra.database.scenes import upsert as db_up
            from infra.database.pool import get_pool
            db_up(get_pool(), sid, scene)
        except Exception as e:
            logger.warning(f"DB 写入跳过: {e}")
        saved.append(scene)

    return {"status": "done", "count": len(saved), "scenes": saved}


# ══════════════════════════════════════════════════════════
# 4.1 对话式编辑 — LLM Chat Edit
# ══════════════════════════════════════════════════════════




@app.task(bind=True, name="ai_chat_edit", soft_time_limit=300)
def ai_chat_edit_task(self, config_path: str, episode: int, message: str, current_shots: list) -> dict:
    """对话式编辑分镜 — 用自然语言修改分镜表"""
    self.update_state(state="PROGRESS", meta={"step": "chat_edit", "progress": 10, "message": "正在初始化 LLM..."})

    cfg, cont = _init_ctx(config_path)
    try:
        llm = cont.get("llm")
    except Exception as e:
        return {"status": "error", "reason": f"LLM 初始化失败: {e}"}

    self.update_state(state="PROGRESS", meta={"step": "chat_edit", "progress": 30, "message": "AI 正在理解指令..."})

    # 构建 prompt（限制 shots 数量避免超出 LLM context window）
    MAX_SHOTS_FOR_EDIT = 50
    shots_for_prompt = current_shots
    truncation_note = ""
    if len(current_shots) > MAX_SHOTS_FOR_EDIT:
        shots_for_prompt = current_shots[:MAX_SHOTS_FOR_EDIT]
        truncation_note = f"\n注意：分镜表共 {len(current_shots)} 个镜头，此处只显示前 {MAX_SHOTS_FOR_EDIT} 个。"
    shots_json = json.dumps(shots_for_prompt, ensure_ascii=False, indent=2)
    prompt = f"""你是一个分镜表编辑助手。用户会用自然语言描述对分镜表的修改需求。
当前分镜表（JSON 格式）：
{shots_json}{truncation_note}

用户指令：{message}

请根据用户的指令修改分镜表，返回修改后的完整分镜表 JSON 数组。
只返回 JSON 数组，不要其他文字。确保所有字段都保留。
如果用户的指令不清晰或无法执行，返回一个 JSON 对象：{{"error": "原因说明"}}"""

    try:
        response = llm.chat(prompt)
        result = parse_llm_json(response)

        if result is None:
            logger.warning(f"chat_edit JSON 解析失败，原始响应: {response[:500]}")
            return {"status": "error", "reason": "LLM 返回的不是有效 JSON"}

        if isinstance(result, dict) and "error" in result:
            return {"status": "error", "reason": result["error"]}

        if isinstance(result, list):
            self.update_state(state="PROGRESS", meta={"step": "chat_edit", "progress": 90, "message": "编辑完成"})
            return {"status": "done", "shots": result, "message": f"已修改 {len(result)} 个镜头"}

        return {"status": "error", "reason": "LLM 返回格式不正确"}

    except Exception as e:
        logger.error(f"chat_edit 异常: {e}")
        return {"status": "error", "reason": f"LLM 执行失败: {e}"}


# ══════════════════════════════════════════════════════════
#  Seko 策划案导入（异步，含图片下载）
# ══════════════════════════════════════════════════════════

def _parse_seko_characters(steps: list[dict], elements: list[dict] | None = None) -> list[dict]:
    """从 Seko steps 中解析角色列表，关联 elements 图片"""
    char_step = next((s for s in steps if s.get("step") == "character_design"), None)
    if not char_step:
        return []

    output = char_step.get("stepOutput", "")
    characters = []
    # 按 "- 角色名" 分割
    blocks = re.split(r"\n(?=- )", output)
    for block in blocks:
        block = block.strip()
        if not block.startswith("- "):
            continue
        # 提取角色名和描述（第一行）
        first_line = block.split("\n")[0]
        match = re.match(r"^- ([^：:]+)[：:](.*)", first_line)
        if not match:
            continue
        char_name = match.group(1).strip()
        char_desc = match.group(2).strip()

        # 提取 Prompt
        prompt_match = re.search(r"<Prompt>(.*?)</Prompt>", block, re.DOTALL)
        prompt_text = prompt_match.group(1).strip() if prompt_match else ""

        # 生成 ID：名字转 safe id
        safe_id = "".join(c for c in char_name if c.isalnum() or c in ("-", "_")).strip()
        if not safe_id:
            safe_id = f"char_{len(characters) + 1:02d}"

        # 查找对应的 element 图片 URL
        seko_image_url = ""
        if elements:
            char_element = next(
                (e for e in elements if e.get("elementType") == "CHARACTER" and (e.get("elementName") or "").strip() == char_name),
                None,
            )
            if char_element and char_element.get("elementUrl"):
                seko_image_url = char_element["elementUrl"]

        characters.append({
            "id": safe_id,
            "name": char_name,
            "appearance": char_desc,
            "prompt": prompt_text,
            "source": "seko",
            "seko_image_url": seko_image_url,
        })

    return characters


def _parse_seko_scenes(steps: list[dict], elements: list[dict] | None = None) -> list[dict]:
    """从 Seko steps 中解析场景列表，关联 elements 图片"""
    scene_step = next((s for s in steps if s.get("step") == "scene_design"), None)
    if not scene_step:
        return []

    output = scene_step.get("stepOutput", "")
    scenes = []
    blocks = re.split(r"\n(?=- )", output)
    for block in blocks:
        block = block.strip()
        if not block.startswith("- "):
            continue
        first_line = block.split("\n")[0]
        match = re.match(r"^- ([^：:]+)[：:](.*)", first_line)
        if not match:
            continue
        scene_name = match.group(1).strip()
        scene_desc = match.group(2).strip()

        prompt_match = re.search(r"<Prompt>(.*?)</Prompt>", block, re.DOTALL)
        prompt_text = prompt_match.group(1).strip() if prompt_match else ""

        safe_id = "".join(c for c in scene_name if c.isalnum() or c in ("-", "_")).strip()
        if not safe_id:
            safe_id = f"scene_{len(scenes) + 1:02d}"

        # 查找对应的 element 图片 URL
        seko_image_url = ""
        if elements:
            scene_element = next(
                (e for e in elements if e.get("elementType") == "SCENE" and (e.get("elementName") or "").strip() == scene_name),
                None,
            )
            if scene_element and scene_element.get("elementUrl"):
                seko_image_url = scene_element["elementUrl"]

        scenes.append({
            "id": safe_id,
            "name": scene_name,
            "description": scene_desc,
            "prompt": prompt_text,
            "source": "seko",
            "seko_image_url": seko_image_url,
        })

    return scenes


def _parse_seko_storyboard(steps: list[dict], episode: int) -> list[dict]:
    """从 Seko steps 中解析分镜表"""
    sb_step = next((s for s in steps if s.get("step") == "storyboard"), None)
    if not sb_step:
        return []

    output = sb_step.get("stepOutput", "")
    shots = []

    # 按 :::shot{name="..."} 分割
    shot_blocks = re.findall(r':::shot\{name="([^"]+)"\}(.*?):::', output, re.DOTALL)
    for shot_name, block in shot_blocks:
        shot_id_match = re.search(r"镜头(\d+)", shot_name)
        shot_id = shot_id_match.group(1).zfill(3) if shot_id_match else f"{len(shots) + 1:03d}"

        # 提取镜头描述
        desc_match = re.search(r":editable\[(.*?)\]", block, re.DOTALL)
        desc_raw = desc_match.group(1).strip() if desc_match else ""

        # 解析描述中的各字段
        scene = ""
        characters = ""
        action = ""
        dialogue = ""
        camera = ""
        shot_type = ""
        duration = 4

        # 场景
        scene_match = re.search(r"场景[：:]\s*(.+?)(?:\n|$)", desc_raw)
        if scene_match:
            scene = scene_match.group(1).strip()

        # 画面描述
        action_match = re.search(r"画面[：:]\s*\[(.+?)\]\s*(.+?)(?:\n运镜|$)", desc_raw, re.DOTALL)
        if action_match:
            shot_type = action_match.group(1).strip()
            action = action_match.group(2).strip().replace("\n", " ").strip()

        # 运镜
        camera_match = re.search(r"运镜[：:]\s*(.+?)(?:\n|$)", desc_raw)
        if camera_match:
            camera = camera_match.group(1).strip()

        # 台词
        dialogue_match = re.search(r"中文配音[：:]\s*\[([^\]]+)\]\s*(.+?)(?:\n|$)", block)
        if dialogue_match:
            char_name = dialogue_match.group(1).strip()
            dialogue = dialogue_match.group(2).strip()
            characters = char_name

        shots.append({
            "episode": str(episode),
            "shot_id": shot_id,
            "scene": scene,
            "characters": characters,
            "action": action,
            "dialogue": dialogue,
            "camera": camera,
            "shot_type": shot_type,
            "duration": str(duration),
            "outfit": "",
            "emotion": "",
            "action_en": "",
            "dialogue_en": "",
        })

    return shots


def _download_seko_image(url: str, output_path: str, timeout: int = 60, retries: int = 3) -> bool:
    """下载单张 Seko 图片（指数退避重试）"""
    import urllib.request
    import urllib.parse
    import time as _time

    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; ai-drama-pipeline/2.0)"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "wb") as f:
                    while True:
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
            logger.info(f"Seko 图片下载成功: {output_path}")
            return True
        except Exception as e:
            if attempt < retries - 1:
                wait = 2 ** attempt
                logger.warning(f"Seko 图片下载失败 (尝试 {attempt + 1}/{retries}), {wait}s 后重试: {e}")
                _time.sleep(wait)
            else:
                logger.warning(f"Seko 图片下载失败 {url}: {e}")
    return False


@app.task(bind=True, name="pipeline.seko.import", soft_time_limit=900)
def seko_import_task(
    self,
    config_path: str,
    proposal_data: dict,
    episode: int = 1,
    import_characters: bool = True,
    import_scenes: bool = True,
    import_storyboard: bool = True,
    download_images: bool = True,
) -> dict:
    """Seko 策划案导入任务（异步）

    解析 Seko 返回的策划案 JSON，将角色/场景/分镜导入项目，
    并异步下载关联图片。
    """
    _ensure_path()

    steps = proposal_data.get("steps", [])
    elements = proposal_data.get("elements", [])
    project_dir = _cfg_dir(config_path)
    result = {"characters": 0, "scenes": 0, "shots": 0, "images_downloaded": 0, "images_failed": 0}

    # ── 1. 导入角色 ──
    if import_characters:
        self.update_state(state="PROGRESS", meta={"step": "seko_import", "progress": 10, "message": "解析角色..."})
        chars = _parse_seko_characters(steps, elements)
        char_dir = project_dir / "config" / "characters"
        char_dir.mkdir(parents=True, exist_ok=True)

        for char in chars:
            cid = char["id"]
            # 构建 YAML 数据（含前端需要的 outfits/voice 字段）
            char_yaml = {
                "id": cid,
                "name": char.get("name", ""),
                "appearance": char.get("appearance", ""),
                "outfits": {"default": {"description": "", "reference_images": []}},
                "voice": {"voice_description": ""},
                "reference_images": [],
                "source": "seko",
            }
            if char.get("seko_image_url"):
                char_yaml["seko_image_url"] = char["seko_image_url"]

            path = char_dir / f"{cid}.yaml"
            from infra.config import save_yaml
            save_yaml(path, {"character": char_yaml})

            # 同步数据库
            try:
                from infra.database.characters import upsert as db_up
                from infra.database.pool import get_pool
                db_up(get_pool(), cid, char_yaml)
            except Exception as e:
                logger.warning(f"DB 写入跳过: {e}")

            result["characters"] += 1

    # ── 2. 导入场景 ──
    if import_scenes:
        self.update_state(state="PROGRESS", meta={"step": "seko_import", "progress": 30, "message": "解析场景..."})
        scenes = _parse_seko_scenes(steps, elements)
        scene_dir = project_dir / "config" / "scenes"
        scene_dir.mkdir(parents=True, exist_ok=True)

        for scene in scenes:
            sid = scene["id"]
            # 构建 YAML 数据（含前端需要的 lighting 字段）
            scene_yaml = {
                "id": sid,
                "name": scene.get("name", ""),
                "description": scene.get("description", ""),
                "lighting": "",
                "reference_images": [],
                "source": "seko",
            }
            if scene.get("seko_image_url"):
                scene_yaml["seko_image_url"] = scene["seko_image_url"]

            path = scene_dir / f"{sid}.yaml"
            from infra.config import save_yaml
            save_yaml(path, {"scene": scene_yaml})

            try:
                from infra.database.scenes import upsert as db_up
                from infra.database.pool import get_pool
                db_up(get_pool(), sid, scene_yaml)
            except Exception as e:
                logger.warning(f"DB 写入跳过: {e}")

            result["scenes"] += 1

    # ── 3. 导入分镜 ──
    # 先构建 name → id 映射（角色/场景导入后、分镜导入前）
    _char_id_map: dict[str, str] = {}
    _scene_id_map: dict[str, str] = {}
    if import_characters:
        for c in chars:
            _char_id_map[c["name"]] = c["id"]
    if import_scenes:
        for s in scenes:
            _scene_id_map[s["name"]] = s["id"]

    if import_storyboard:
        self.update_state(state="PROGRESS", meta={"step": "seko_import", "progress": 50, "message": "解析分镜..."})
        shots = _parse_seko_storyboard(steps, episode)
        if shots:
            # 映射角色名 → 角色 ID，场景名 → 场景 ID
            for shot in shots:
                chars_field = shot.get("characters", "")
                if chars_field:
                    mapped = []
                    for cname in [c.strip() for c in chars_field.split("+") if c.strip()]:
                        mapped.append(_char_id_map.get(cname, cname))
                    shot["characters"] = "+".join(mapped)
                scene_field = shot.get("scene", "")
                if scene_field and scene_field in _scene_id_map:
                    shot["scene"] = _scene_id_map[scene_field]

            sb_path = project_dir / "storyboard" / "episodes.csv"
            from engines.storyboard import save_storyboard
            save_storyboard(sb_path, shots, episode, append=True)

            # 同步数据库
            try:
                from infra.database.pool import get_pool
                from infra.database.shots import upsert as db_upsert_shot
                pool = get_pool()
                for shot in shots:
                    sid = shot.get("shot_id", "")
                    if sid:
                        db_upsert_shot(pool, episode, sid, shot)
            except Exception as e:
                logger.warning(f"DB 写入跳过: {e}")

            result["shots"] = len(shots)

    # ── 4. 异步下载图片 ──
    # _char_id_map 和 _scene_id_map 已在上方构建

    if download_images and elements:
        self.update_state(state="PROGRESS", meta={"step": "seko_import", "progress": 70, "message": "下载图片..."})
        total = len(elements)
        for idx, elem in enumerate(elements):
            url = elem.get("elementUrl")
            name = (elem.get("elementName") or "").strip()
            elem_type = elem.get("elementType", "")
            if not url or not name:
                continue

            # 使用与 YAML 文件一致的 ID 作为目录名
            if elem_type == "CHARACTER":
                entity_id = _char_id_map.get(name)
                if not entity_id:
                    # 回退：在已导入的 YAML 中按 name 字段查找
                    for yf in (project_dir / "config" / "characters").glob("*.yaml"):
                        try:
                            yd = yaml.safe_load(yf) or {}
                            if yd.get("character", {}).get("name") == name:
                                entity_id = yd["character"]["id"]
                                break
                        except Exception:
                            pass
                if not entity_id:
                    entity_id = "".join(c for c in name if c.isalnum() or c in ("-", "_")).strip() or f"char_{idx + 1:02d}"
                img_dir = project_dir / "assets" / "characters" / entity_id
                yaml_path = project_dir / "config" / "characters" / f"{entity_id}.yaml"
                asset_type = "characters"
                entity_key = "character"
            elif elem_type == "SCENE":
                entity_id = _scene_id_map.get(name)
                if not entity_id:
                    for yf in (project_dir / "config" / "scenes").glob("*.yaml"):
                        try:
                            yd = yaml.safe_load(yf) or {}
                            if yd.get("scene", {}).get("name") == name:
                                entity_id = yd["scene"]["id"]
                                break
                        except Exception:
                            pass
                if not entity_id:
                    entity_id = "".join(c for c in name if c.isalnum() or c in ("-", "_")).strip() or f"scene_{idx + 1:02d}"
                img_dir = project_dir / "assets" / "scenes" / entity_id
                yaml_path = project_dir / "config" / "scenes" / f"{entity_id}.yaml"
                asset_type = "scenes"
                entity_key = "scene"
            else:
                img_dir = project_dir / "assets" / "seko"
                yaml_path = None
                asset_type = "seko"
                entity_key = ""

            img_dir.mkdir(parents=True, exist_ok=True)
            img_path = img_dir / "cover.png"

            progress = int(70 + (idx + 1) / total * 25)
            self.update_state(state="PROGRESS", meta={
                "step": "seko_import", "progress": progress,
                "message": f"下载图片 [{idx + 1}/{total}] {name}...",
            })

            if _download_seko_image(url, str(img_path)):
                result["images_downloaded"] += 1
                # 更新 YAML 中的 reference_images
                if yaml_path and yaml_path.exists():
                    try:
                        with open(yaml_path, encoding="utf-8") as f:
                            data = yaml.safe_load(f) or {}
                        entity = data.get(entity_key, {})
                        entity["reference_images"] = [f"/api/assets/{asset_type}/{entity_id}/cover.png"]
                        data[entity_key] = entity
                        from infra.config import save_yaml
                        save_yaml(yaml_path, data)
                    except Exception as e:
                        logger.debug(f"更新 YAML reference_images 失败: {e}")
            else:
                result["images_failed"] += 1

    self.update_state(state="PROGRESS", meta={"step": "seko_import", "progress": 100, "message": "导入完成"})
    return {"status": "done", **result}


# ══════════════════════════════════════════════════════════
#  LoRA 训练任务
# ══════════════════════════════════════════════════════════

@app.task(bind=True, name="pipeline.train_lora", soft_time_limit=7200)
def train_lora_task(self, config_path: str, char_id: str, *,
                    trigger_word: str = "", steps: int = 1000,
                    learning_rate: float = 1e-4, rank: int = 16,
                    resolution: str = "512x768", force: bool = False) -> dict:
    """为角色训练 LoRA 模型（异步）"""
    _ensure_path()

    # ── 防重复：同一角色同一时间只能有一个训练任务 ──
    # 使用 episode=0 + shot_id=char_id 作为锁键，与其他任务的锁空间隔离
    if not force and not _try_mark_running_atomic(config_path, 0, char_id, "train_lora"):
        return {"status": "skipped", "reason": f"角色 {char_id} 的 LoRA 训练已在执行中，请等待完成"}
    if force:
        _db_mark_running(config_path, 0, char_id, "train_lora")

    self.update_state(state="PROGRESS", meta={
        "step": "train_lora", "progress": 5,
        "message": f"准备训练 {char_id} 的 LoRA..."})

    cfg, cont = _init_ctx(config_path)
    project_dir = _cfg_dir(config_path)
    from infra.asset_tracker import comfyui_asset_name

    # 检查角色是否存在
    char_yaml_path = project_dir / "config" / "characters" / f"{char_id}.yaml"
    if not char_yaml_path.exists():
        _db_record_step(config_path, 0, char_id, "train_lora",
                        {"status": "error", "reason": f"角色 {char_id} 不存在"})
        return {"status": "error", "reason": f"角色 {char_id} 不存在"}

    # 检查是否已有 LoRA（多候选路径查找）
    lora_dir = project_dir / "assets" / "loras"
    lora_filename = comfyui_asset_name(str(project_dir), char_id, f"{char_id}_lora.safetensors")
    lora_candidates = [
        lora_dir / lora_filename,                        # proj_{hash}_{char_id}_lora.safetensors
        lora_dir / f"{char_id}_lora.safetensors",        # {char_id}_lora.safetensors
        lora_dir / f"{char_id}.safetensors",             # {char_id}.safetensors
    ]
    lora_path = None
    for p in lora_candidates:
        if p.exists():
            lora_path = p
            break
    if lora_path and not force:
        _db_record_step(config_path, 0, char_id, "train_lora",
                        {"status": "skipped", "reason": f"LoRA 已存在: {lora_path.name}"})
        return {"status": "skipped", "reason": f"LoRA 已存在: {lora_path.name}，使用 force 覆盖"}

    # 收集训练图片（角色定妆照 + outfit 图片）
    char_assets_dir = project_dir / "assets" / "characters" / char_id
    if not char_assets_dir.exists():
        return {"status": "error", "reason": f"角色 {char_id} 无定妆照，请先生成定妆照"}

    # 统计图片数量
    img_count = 0
    for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
        img_count += len(list(char_assets_dir.glob(ext)))
        # 也收集 outfit 子目录的图片
        for outfit_dir in char_assets_dir.iterdir():
            if outfit_dir.is_dir():
                img_count += len(list(outfit_dir.glob(ext)))

    if img_count < 3:
        _db_record_step(config_path, 0, char_id, "train_lora",
                        {"status": "error", "reason": f"训练图片不足（{img_count} 张），至少需要 3 张"})
        return {"status": "error", "reason": f"训练图片不足（{img_count} 张），至少需要 3 张"}

    self.update_state(state="PROGRESS", meta={
        "step": "train_lora", "progress": 15,
        "message": f"找到 {img_count} 张训练图片，开始训练..."})

    # 获取训练后端
    try:
        trainer = cont.get("training")
    except Exception as e:
        _db_record_step(config_path, 0, char_id, "train_lora",
                        {"status": "error", "reason": f"训练后端不可用: {e}"})
        return {"status": "error", "reason": f"训练后端不可用: {e}"}

    # 读取角色名作为默认触发词
    if not trigger_word:
        try:
            with open(char_yaml_path, encoding="utf-8") as f:
                char_data = yaml.safe_load(f) or {}
            char_name = char_data.get("character", {}).get("name", char_id)
            trigger_word = f"ohwx {char_name}"
        except Exception:
            trigger_word = f"ohwx {char_id}"

    # 执行训练
    try:
        result_path = trainer.train_lora(
            char_id, str(char_assets_dir),
            trigger_word=trigger_word,
            steps=steps,
            learning_rate=learning_rate,
            rank=rank,
            resolution=resolution,
            output_name=f"{char_id}_lora",
        )
    except Exception as e:
        logger.error(f"LoRA 训练失败: {e}")
        _db_record_step(config_path, 0, char_id, "train_lora",
                        {"status": "error", "reason": f"训练失败: {e}"})
        return {"status": "error", "reason": f"训练失败: {e}"}

    self.update_state(state="PROGRESS", meta={
        "step": "train_lora", "progress": 95,
        "message": "训练完成，更新角色配置..."})

    # 重命名 LoRA 文件：加 project_dir hash 前缀，避免跨项目同名角色 LoRA 覆盖
    original_name = Path(result_path).name
    new_name = comfyui_asset_name(str(project_dir), char_id, original_name)
    new_path = Path(result_path).parent / new_name
    if Path(result_path).exists() and not new_path.exists():
        os.replace(result_path, str(new_path))
        result_path = str(new_path)
        logger.info(f"LoRA 已重命名: {original_name} → {new_name}")

    # 更新角色 YAML，标记 LoRA 路径
    try:
        with open(char_yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        char = data.get("character", {})
        char["lora_path"] = result_path
        data["character"] = char
        from infra.config import save_yaml
        save_yaml(char_yaml_path, data)
    except Exception as e:
        logger.warning(f"更新角色 LoRA 路径失败: {e}")

    _db_record_step(config_path, 0, char_id, "train_lora",
                    {"status": "done", "path": result_path})
    return {"status": "done", "char_id": char_id, "lora_path": result_path,
            "trigger_word": trigger_word, "steps": steps, "images": img_count}


# ══════════════════════════════════════════════════════════
#  准备阶段 — 批量预翻译（LLM 密集，一次性）
# ══════════════════════════════════════════════════════════

@app.task(bind=True, name="pipeline.ai.prepare", soft_time_limit=1800)
def ai_prepare_task(self, config_path: str, episode: int = 1, *,
                    force: bool = False,
                    translate: bool = True) -> dict:
    """准备阶段 — 批量预翻译

    在生产管线之前运行，将所有 LLM 翻译操作集中完成。
    运行完毕后，生产管线可完全不依赖 LLM 全速运行。
    定妆照和场景图请通过 Web 工作台单独执行。

    Args:
        config_path: 项目配置路径
        episode: 集数
        force: True 时覆盖已有翻译
        translate: 是否批量翻译
    """
    _ensure_path()

    self.update_state(state="PROGRESS", meta={
        "step": "prepare", "progress": 5, "message": "初始化..."})

    cfg, cont = _init_ctx(config_path)
    project_dir = _cfg_dir(config_path)

    # 获取 LLM 实例
    llm = None
    try:
        if cfg.get("llm", {}).get("enabled"):
            llm = cont.get("llm")
    except Exception as e:
        if translate:
            logger.warning(f"LLM 不可用，跳过翻译: {e}")

    from engines.prompt import translate_to_english, batch_translate_to_english
    from infra.config import save_yaml

    # 批量翻译开关（config: llm.batch_translate，默认 True）
    use_batch = cfg.get("llm.batch_translate", True)
    if use_batch:
        logger.info("  批量翻译模式: ON")
    else:
        logger.info("  批量翻译模式: OFF")

    result = {
        "translated_chars": 0, "translated_scenes": 0, "translated_shots": 0,
        "view_split_chars": 0,
    }

    def _single(text: str) -> str:
        return translate_to_english(text, llm=llm)

    # ── 1. 翻译角色描述 ──
    if translate and llm:
        self.update_state(state="PROGRESS", meta={
            "step": "prepare", "progress": 10, "message": "翻译角色描述..."})

        char_dir = project_dir / "config" / "characters"
        if char_dir.exists():
            # 收集待翻译: [(file, data, field_path, text)]
            pending: list[tuple[Path, dict, list[str], str]] = []
            all_char_files: list[tuple[Path, dict]] = []

            for f in char_dir.glob("*.yaml"):
                if f.stem.endswith(".example"):
                    continue
                try:
                    with open(f, encoding="utf-8") as fh:
                        data = yaml.safe_load(fh) or {}
                except Exception:
                    continue
                char = data.get("character", {})
                if not char.get("id"):
                    continue
                all_char_files.append((f, data))

                appearance = char.get("appearance", "")
                if appearance and (not char.get("appearance_en") or force):
                    if any(ord(c) > 127 for c in appearance):
                        pending.append((f, data, ["appearance_en"], appearance))

                voice = char.get("voice", {})
                if isinstance(voice, dict):
                    vd = voice.get("voice_description", "")
                    if vd and (not voice.get("voice_description_en") or force):
                        if any(ord(c) > 127 for c in vd):
                            pending.append((f, data, ["voice", "voice_description_en"], vd))

                outfits = char.get("outfits", {})
                if isinstance(outfits, dict):
                    for ok, ov in outfits.items():
                        if isinstance(ov, dict):
                            od = ov.get("description", "")
                            if od and (not ov.get("description_en") or force):
                                if any(ord(c) > 127 for c in od):
                                    pending.append((f, data, ["outfits", ok, "description_en"], od))

            if pending:
                texts = [p[3] for p in pending]
                translations = batch_translate_to_english(texts, llm=llm) if use_batch else [_single(t) for t in texts]

                for (_, file_data, field_path, _), translated in zip(pending, translations):
                    if not translated:
                        continue
                    obj = file_data.get("character", file_data)
                    for key in field_path[:-1]:
                        obj = obj.setdefault(key, {}) if isinstance(obj, dict) else obj
                    if isinstance(obj, dict):
                        obj[field_path[-1]] = translated
                    result["translated_chars"] += 1

                seen: set[str] = set()
                for f, data in all_char_files:
                    sp = str(f)
                    if sp not in seen:
                        seen.add(sp)
                        save_yaml(f, data)
                logger.info(f"  翻译角色: {result['translated_chars']} 条")

    # ── 1b. 生成视角专属外貌描述（逐条，不批量） ──
    if translate and llm:
        self.update_state(state="PROGRESS", meta={
            "step": "prepare", "progress": 20, "message": "生成视角专属描述..."})

        from engines.prompt import generate_view_prompts

        char_dir = project_dir / "config" / "characters"
        if char_dir.exists():
            for f in char_dir.glob("*.yaml"):
                if f.stem.endswith(".example"):
                    continue
                try:
                    with open(f, encoding="utf-8") as fh:
                        data = yaml.safe_load(fh) or {}
                except Exception:
                    continue
                char = data.get("character", {})
                if not char.get("id"):
                    continue

                appearance = char.get("appearance", "")
                has_view_prompts = all(char.get(f"appearance_{v}_en") for v in ("front", "side", "back"))

                if appearance and (not has_view_prompts or force):
                    if any(ord(c) > 127 for c in appearance):
                        view_prompts = generate_view_prompts(appearance, llm)
                        if view_prompts:
                            char["appearance_front_en"] = view_prompts["front"]
                            char["appearance_side_en"] = view_prompts["side"]
                            char["appearance_back_en"] = view_prompts["back"]
                            data["character"] = char
                            save_yaml(f, data)
                            result["view_split_chars"] += 1
                            logger.info(f"  视角拆分 {char.get('id')}: front/side/back")

    # ── 2. 翻译场景描述 ──
    if translate and llm:
        self.update_state(state="PROGRESS", meta={
            "step": "prepare", "progress": 30, "message": "翻译场景描述..."})

        scene_dir = project_dir / "config" / "scenes"
        if scene_dir.exists():
            pending: list[tuple[Path, dict, list[str], str]] = []
            all_scene_files: list[tuple[Path, dict]] = []

            for f in scene_dir.glob("*.yaml"):
                if f.stem.endswith(".example"):
                    continue
                try:
                    with open(f, encoding="utf-8") as fh:
                        data = yaml.safe_load(fh) or {}
                except Exception:
                    continue
                scene = data.get("scene", {})
                if not scene.get("id"):
                    continue
                all_scene_files.append((f, data))

                desc = scene.get("description", "")
                if desc and (not scene.get("description_en") or force):
                    if any(ord(c) > 127 for c in desc):
                        pending.append((f, data, ["description_en"], desc))

                lighting = scene.get("lighting", "")
                if lighting and (not scene.get("lighting_en") or force):
                    if any(ord(c) > 127 for c in lighting):
                        pending.append((f, data, ["lighting_en"], lighting))

            if pending:
                texts = [p[3] for p in pending]
                translations = batch_translate_to_english(texts, llm=llm) if use_batch else [_single(t) for t in texts]

                for (_, file_data, field_path, _), translated in zip(pending, translations):
                    if not translated:
                        continue
                    scene_obj = file_data.get("scene", file_data)
                    scene_obj[field_path[-1]] = translated
                    result["translated_scenes"] += 1

                seen: set[str] = set()
                for f, data in all_scene_files:
                    sp = str(f)
                    if sp not in seen:
                        seen.add(sp)
                        save_yaml(f, data)
                logger.info(f"  翻译场景: {result['translated_scenes']} 条")

    # ── 3. 翻译分镜动作/台词 ──
    if translate and llm:
        self.update_state(state="PROGRESS", meta={
            "step": "prepare", "progress": 50, "message": "翻译分镜..."})

        sb_path = project_dir / "storyboard" / "episodes.csv"
        if sb_path.exists():
            import csv as _csv
            shots = []
            with open(sb_path, encoding="utf-8") as fh:
                shots = [dict(r) for r in _csv.DictReader(fh)]

            # 收集本集待翻译
            shot_pending: list[tuple[int, str, str]] = []  # (shot_idx, field, text)
            for si, shot in enumerate(shots):
                ep = int(shot.get("episode", 0) or 0)
                if ep != episode:
                    continue
                action = shot.get("action", "")
                if action and (not shot.get("action_en") or force):
                    if any(ord(c) > 127 for c in action):
                        from engines.prompt import _strip_dialogue
                        shot_pending.append((si, "action_en", _strip_dialogue(action)))
                dialogue = shot.get("dialogue", "")
                if dialogue and dialogue != "......" and (not shot.get("dialogue_en") or force):
                    if any(ord(c) > 127 for c in dialogue):
                        shot_pending.append((si, "dialogue_en", dialogue))

            if shot_pending:
                texts = [p[2] for p in shot_pending]
                translations = batch_translate_to_english(texts, llm=llm) if use_batch else [_single(t) for t in texts]

                changed = False
                for (si, field, _), translated in zip(shot_pending, translations):
                    if translated:
                        shots[si][field] = translated
                        changed = True
                        result["translated_shots"] += 1

                if changed:
                    from engines.storyboard import save_storyboard
                    save_storyboard(sb_path, shots, episode, append=True)
                    logger.info(f"  翻译分镜: {result['translated_shots']} 条")

    self.update_state(state="PROGRESS", meta={
        "step": "prepare", "progress": 100, "message": "准备完成"})

    total = result["translated_chars"] + result["translated_scenes"] + result["translated_shots"] + result["view_split_chars"]
    logger.info(f"准备阶段完成: {result}")
    return {"status": "done", **result, "total_operations": total}

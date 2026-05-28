"""Celery 任务定义 — 每步独立，按需执行"""
from __future__ import annotations

import csv
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

from pipeline.celery_app import app

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
        conn = pool.connect()
        cur = conn.cursor()
        import zlib
        lock_key = zlib.crc32(f"gen:{episode}:{shot_id}:{step}".encode()) & 0x7FFFFFFF
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
                try:
                    conn.commit()
                except Exception:
                    pass
        finally:
            pool.release(conn)
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

def _prepare(config_path: str, episode: int, shot_id: str, step: str, tool: str, *, need_shot: bool = True):
    """防重复 → 工具可用 → 查镜头 → 标记运行 → 返回 (cfg, cont, shot, err)"""
    _ensure_path()
    # 使用原子操作检查+标记，避免竞态条件
    if not _try_mark_running_atomic(config_path, episode, shot_id, step):
        return None, None, None, _skip(shot_id, step, "该步骤正在执行中")
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
    import hashlib
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

    llm = None
    try:
        if cfg.get("llm", {}).get("enabled"):
            llm = cont.get("llm")
    except Exception:
        pass

    char_descs = [translate_to_english(sm.get_character(cid).get("appearance", ""), llm=llm)
                  for cid in char_ids if sm.get_character(cid)]
    scene = sm.get_scene(shot.get("scene", ""))
    scene_desc = translate_to_english(scene.get("description", ""), llm=llm) if scene else ""

    multi_char_prompt = ""
    if len(char_ids) > 1:
        multi_char_prompt = MultiCharacterHandler().generate_multi_char_prompt(
            [c for c in (sm.get_character(cid) for cid in char_ids) if c])

    wb = WorkflowBuilder(cfg.data, cfg.get("models", {}), cfg.project_dir, comfyui=cont.get("image"))
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
    for node_id, file_path in wb.build_upload_map(shot, wf).items():
        if Path(file_path).exists():
            try:
                comfyui.upload_image(file_path)
                if node_id in wf and wf[node_id].get("class_type") in ("LoadImage", "LoadImageFromPath", "ImageLoad"):
                    wf[node_id]["inputs"]["image"] = Path(file_path).name
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


def video_core(shot_id: str, cfg, cont, out_dir: Path, *, force: bool = False) -> dict:
    """视频生成核心逻辑 — 从首帧生成视频

    Args:
        shot_id: 镜头 ID
        cfg: Config 对象
        cont: DI 容器
        out_dir: 输出目录
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
    video_wf = wb.build_video(str(frame_path))
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
    import hashlib as _hashlib
    import re as _re
    if _re.search(r'[^\x00-\x7f]', project_name):
        # 含非 ASCII 字符（如中文）：用原名的短 hash 替代，确保唯一且纯 ASCII
        ascii_name = "proj_" + _hashlib.md5(project_name.encode("utf-8")).hexdigest()[:8]
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
                if video_comfyui.check_image_exists(server_filename):
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
    cfg, cont, shot, err = _prepare(config_path, episode, shot_id, "tts", "tts")
    if err:
        return err
    return tts_core(shot_id, shot, cfg, cont, _shot_dir(config_path, episode, shot_id), force=force)


def _run_first_frame(config_path: str, episode: int, shot_id: str, *, force: bool = False) -> dict:
    cfg, cont, shot, err = _prepare(config_path, episode, shot_id, "first_frame", "comfyui")
    if err:
        return err
    return first_frame_core(shot_id, shot, cfg, cont, _shot_dir(config_path, episode, shot_id), force=force)


def _run_video(config_path: str, episode: int, shot_id: str, *, force: bool = False) -> dict:
    cfg, cont, _, err = _prepare(config_path, episode, shot_id, "video", "comfyui", need_shot=False)
    if err:
        return err
    return video_core(shot_id, cfg, cont, _shot_dir(config_path, episode, shot_id), force=force)


def _run_lipsync(config_path: str, episode: int, shot_id: str, *, force: bool = False) -> dict:
    cfg, cont, _, err = _prepare(config_path, episode, shot_id, "lipsync", "lipsync", need_shot=False)
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
    base_frames = gen.get("video_frames", 8)
    if preset == "high":
        overrides = {
            "image_steps": int(base_steps * 1.4),
            "resolution": [min(1920, int(base_res[0] * 1.5)), min(1080, int(base_res[1] * 1.5))],
            "video_frames": min(16, int(base_frames * 2)),
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
    self.update_state(state="PROGRESS", meta={"step": "scene_images", "progress": 10, "message": "加载场景..."})
    try:
        from engines.workflow_builder import WorkflowBuilder
        from engines.prompt import translate_to_english
        from infra.config import Config
        from api import _ensure_registered; _ensure_registered()
        from api.registry import Container
        import yaml

        cfg = Config(config_path)
        cont = Container(cfg.data)
        comfyui = cont.get("image")

        llm = None
        try:
            if cfg.get("llm", {}).get("enabled"):
                llm = cont.get("llm")
        except Exception:
            pass

        scenes_dir = Path(cfg.project_dir) / "config" / "scenes"
        if not scenes_dir.exists():
            return {"status": "error", "reason": "场景配置目录不存在"}

        scene_files = [f for f in scenes_dir.glob("*.yaml") if not f.stem.endswith(".example")]
        if not scene_files:
            return {"status": "error", "reason": "没有场景配置"}

        models = cfg.get("models", {})
        wb = WorkflowBuilder(cfg.data, models, cfg.project_dir, comfyui=comfyui)
        wb.load_workflows()

        generated = 0
        total = len(scene_files)
        for i, f in enumerate(scene_files):
            try:
                with open(f, encoding="utf-8") as fh:
                    data = yaml.safe_load(fh) or {}
            except yaml.YAMLError as e:
                logger.warning(f"场景 YAML 格式错误 {f}: {e}")
                continue
            scene = data.get("scene", {})
            sid = scene.get("id", f.stem)
            sname = scene.get("name", sid)
            description = scene.get("description", "")

            self.update_state(state="PROGRESS", meta={
                "step": "scene_images", "progress": int(10 + i / total * 80),
                "message": f"[{i+1}/{total}] {sname}",
                "current": i + 1, "total": total})

            # 跳过已有参考图的场景
            scene_asset_dir = Path(cfg.project_dir) / "assets" / "scenes" / sid
            if scene_asset_dir.exists():
                existing = list(scene_asset_dir.glob("*.png")) + list(scene_asset_dir.glob("*.jpg"))
                if existing:
                    if force:
                        for img in existing:
                            img.unlink()
                        logger.info(f"  场景 {sname} 已有 {len(existing)} 张图，已删除（强制模式）")
                    else:
                        logger.info(f"  场景 {sname} 已有 {len(existing)} 张图，跳过")
                        continue

            scene_asset_dir.mkdir(parents=True, exist_ok=True)
            scene_desc_en = translate_to_english(description, llm=llm)

            fake_shot = {"characters": "", "emotion": "neutral",
                         "shot_type": "全景", "camera": "固定"}
            _, wf = wb.build_first_frame(fake_shot, scene_desc=scene_desc_en)
            if not wf:
                logger.warning(f"  ⚠ 场景 {sname}: 工作流为空")
                continue

            try:
                files = comfyui.generate(wf, str(scene_asset_dir))
                if files:
                    img_url = f"/api/assets/scenes/{sid}/{Path(files[0]).name}"
                    scene.setdefault("reference_images", [])
                    prefix = f"/api/assets/scenes/{sid}/cover"
                    scene["reference_images"] = [u for u in scene["reference_images"] if not u.startswith(prefix)]
                    scene["reference_images"].append(img_url)
                    data["scene"] = scene
                    from infra.config import save_yaml
                    save_yaml(f, data)
                    generated += 1
                    logger.info(f"  ✅ 场景 {sname}: 生成完成")
            except Exception as e:
                logger.error(f"  ❌ 场景 {sname}: {e}")

        return {"status": "done", "generated": generated, "total": total}
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
    import yaml
    from engines.workflow_builder import WorkflowBuilder
    from engines.prompt import translate_to_english

    self.update_state(state="PROGRESS", meta={"step": "portrait", "progress": 10, "message": f"生成 {char_id} 定妆照..."})

    cfg, cont = _init_ctx(config_path)
    project_dir = _cfg_dir(config_path)

    char_yaml_path = project_dir / "config" / "characters" / f"{char_id}.yaml"
    if not char_yaml_path.exists():
        return {"status": "error", "reason": f"角色 {char_id} 不存在"}

    with open(char_yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    char = data.get("character", {})
    appearance = char.get("appearance", char_id)

    try:
        comfyui = cont.get("image")
    except Exception as e:
        return {"status": "error", "reason": f"ComfyUI 不可用: {e}"}

    llm = None
    try:
        if cfg.get("llm", {}).get("enabled"):
            llm = cont.get("llm")
    except Exception:
        pass

    portrait_dir = project_dir / "assets" / "characters" / char_id
    portrait_dir.mkdir(parents=True, exist_ok=True)
    # 只删主图，不动 outfit 子目录
    for old in portrait_dir.glob("*.png"):
        old.unlink()
    for old in portrait_dir.glob("*.jpg"):
        old.unlink()

    models = cfg.get("models", {})
    wb = WorkflowBuilder(cfg.data, models, str(project_dir), comfyui=comfyui, llm=llm)
    wb.load_workflows()

    # ── 1. 生成主定妆照 ──
    fake_shot = {"characters": char_id, "emotion": "neutral",
                 "shot_type": "特写", "camera": "固定"}
    _, wf = wb.build_first_frame(fake_shot, character_desc=appearance)
    if not wf:
        return {"status": "error", "reason": "首帧工作流为空（缺少模板）"}

    self.update_state(state="PROGRESS", meta={"step": "portrait", "progress": 30, "message": "ComfyUI 生成主图..."})
    try:
        files = comfyui.generate(wf, str(portrait_dir))
    except Exception as e:
        return {"status": "error", "reason": f"ComfyUI 生成失败: {e}"}
    if not files:
        return {"status": "error", "reason": "ComfyUI 未返回任何图片"}

    img_url = f"/api/assets/characters/{char_id}/{Path(files[0]).name}"
    char.setdefault("reference_images", [])
    prefix = f"/api/assets/characters/{char_id}/cover"
    char["reference_images"] = [u for u in char["reference_images"] if not u.startswith(prefix)]
    char["reference_images"].append(img_url)

    # ── 2. 遍历服装，生成各 outfit 参考图 ──
    outfits = char.get("outfits", {})
    outfit_results = {}
    if isinstance(outfits, dict) and outfits:
        total = len(outfits)
        for i, (outfit_key, outfit_val) in enumerate(outfits.items()):
            if not isinstance(outfit_val, dict):
                continue
            outfit_desc = outfit_val.get("description", "")
            if not outfit_desc:
                continue

            self.update_state(state="PROGRESS", meta={
                "step": "portrait", "progress": int(30 + i / total * 60),
                "message": f"生成服装 {outfit_key} ({i+1}/{total})..."})

            outfit_dir = portrait_dir / outfit_key
            outfit_dir.mkdir(parents=True, exist_ok=True)
            # 清理旧图
            for old in outfit_dir.glob("*.png"):
                old.unlink()
            for old in outfit_dir.glob("*.jpg"):
                old.unlink()

            full_desc = f"{appearance}, wearing {outfit_desc}"
            if any(ord(c) > 127 for c in full_desc):
                full_desc = translate_to_english(full_desc, llm=llm)

            fake_shot = {"characters": char_id, "emotion": "neutral",
                         "shot_type": "全身", "camera": "固定"}
            _, wf = wb.build_first_frame(fake_shot, character_desc=full_desc)
            if not wf:
                outfit_results[outfit_key] = "工作流为空"
                continue

            try:
                files = comfyui.generate(wf, str(outfit_dir))
                if files:
                    outfit_url = f"/api/assets/characters/{char_id}/{outfit_key}/{Path(files[0]).name}"
                    outfit_val.setdefault("reference_images", [])
                    op = f"/api/assets/characters/{char_id}/{outfit_key}/cover"
                    outfit_val["reference_images"] = [u for u in outfit_val["reference_images"] if not u.startswith(op)]
                    outfit_val["reference_images"].append(outfit_url)
                    outfit_results[outfit_key] = "done"
                else:
                    outfit_results[outfit_key] = "未生成"
            except Exception as e:
                outfit_results[outfit_key] = f"失败: {e}"

    # ── 3. 写回 YAML ──
    data["character"] = char
    from infra.config import save_yaml
    save_yaml(char_yaml_path, data)

    try:
        from infra.database.characters import upsert as db_up
        from infra.database.pool import get_pool
        db_up(get_pool(), char_id, char)
    except Exception as e:
        logger.debug(f"DB 写入跳过: {e}")

    return {"status": "done", "url": img_url, "char_id": char_id}


@app.task(bind=True, name="pipeline.outfit_single", soft_time_limit=300)
def outfit_single_task(self, config_path: str, char_id: str, outfit_key: str) -> dict:
    """为单个角色的指定服装生成参考图（异步）"""
    _ensure_path()
    import yaml
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
    for old in outfit_dir.glob("*.png"):
        old.unlink()
    for old in outfit_dir.glob("*.jpg"):
        old.unlink()

    full_desc = f"{appearance}, wearing {outfit_desc}"
    if any(ord(c) > 127 for c in full_desc):
        full_desc = translate_to_english(full_desc, llm=None)

    models = cfg.get("models", {})
    wb = WorkflowBuilder(cfg.data, models, str(project_dir), comfyui=comfyui)
    wb.load_workflows()
    fake_shot = {"characters": char_id, "emotion": "neutral",
                 "shot_type": "全身", "camera": "固定"}
    _, wf = wb.build_first_frame(fake_shot, character_desc=full_desc)
    if not wf:
        return {"status": "error", "reason": "首帧工作流为空（缺少模板）"}

    self.update_state(state="PROGRESS", meta={"step": "outfit", "progress": 50, "message": "ComfyUI 生成中..."})
    try:
        files = comfyui.generate(wf, str(outfit_dir))
    except Exception as e:
        return {"status": "error", "reason": f"ComfyUI 生成失败: {e}"}
    if not files:
        return {"status": "error", "reason": "ComfyUI 未返回任何图片"}

    img_url = f"/api/assets/characters/{char_id}/{outfit_key}/{Path(files[0]).name}"

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
    import yaml

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
    import yaml
    from engines.workflow_builder import WorkflowBuilder
    from engines.prompt import translate_to_english

    self.update_state(state="PROGRESS", meta={"step": "scene_image", "progress": 10, "message": f"生成场景 {scene_id} 参考图..."})

    cfg, cont = _init_ctx(config_path)
    project_dir = _cfg_dir(config_path)

    scene_yaml_path = project_dir / "config" / "scenes" / f"{scene_id}.yaml"
    if not scene_yaml_path.exists():
        return {"status": "error", "reason": f"场景 {scene_id} 不存在"}

    with open(scene_yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    scene = data.get("scene", {})
    description = scene.get("description", scene_id)

    try:
        comfyui = cont.get("image")
    except Exception as e:
        return {"status": "error", "reason": f"ComfyUI 不可用: {e}"}

    scene_dir = project_dir / "assets" / "scenes" / scene_id
    scene_dir.mkdir(parents=True, exist_ok=True)
    for old in scene_dir.glob("*.png"):
        old.unlink()
    for old in scene_dir.glob("*.jpg"):
        old.unlink()

    llm = None
    try:
        if cfg.get("llm", {}).get("enabled"):
            llm = cont.get("llm")
    except Exception:
        pass

    scene_desc_en = translate_to_english(description, llm=llm)

    models = cfg.get("models", {})
    wb = WorkflowBuilder(cfg.data, models, str(project_dir), comfyui=comfyui)
    wb.load_workflows()
    fake_shot = {"characters": "", "emotion": "neutral",
                 "shot_type": "全景", "camera": "固定"}
    _, wf = wb.build_first_frame(fake_shot, scene_desc=scene_desc_en)
    if not wf:
        return {"status": "error", "reason": "首帧工作流为空（缺少模板）"}

    self.update_state(state="PROGRESS", meta={"step": "scene_image", "progress": 50, "message": "ComfyUI 生成中..."})
    try:
        files = comfyui.generate(wf, str(scene_dir))
    except Exception as e:
        return {"status": "error", "reason": f"ComfyUI 生成失败: {e}"}
    if not files:
        return {"status": "error", "reason": "ComfyUI 未返回任何图片"}

    img_url = f"/api/assets/scenes/{scene_id}/{Path(files[0]).name}"
    scene.setdefault("reference_images", [])
    prefix = f"/api/assets/scenes/{scene_id}/cover"
    scene["reference_images"] = [u for u in scene["reference_images"] if not u.startswith(prefix)]
    scene["reference_images"].append(img_url)
    data["scene"] = scene
    from infra.config import save_yaml
    save_yaml(scene_yaml_path, data)

    try:
        from infra.database.scenes import upsert as db_up
        from infra.database.pool import get_pool
        db_up(get_pool(), scene_id, scene)
    except Exception as e:
        logger.debug(f"DB 写入跳过: {e}")

    return {"status": "done", "url": img_url, "scene_id": scene_id}


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
    import hashlib
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
    import yaml as _yaml

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


def _load_yaml_entities(directory, key: str) -> list:
    """加载目录下所有 YAML 实体"""
    import yaml
    d = Path(directory)
    if not d.exists():
        return []
    result = []
    for f in d.glob("*.yaml"):
        if f.stem.endswith(".example"):
            continue
        try:
            with open(f, encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            entity = data.get(key, {})
            if entity.get("id"):
                result.append(entity)
        except Exception:
            continue
    return result


@app.task(bind=True, name="pipeline.ai.characters", soft_time_limit=300)
def ai_characters_task(self, config_path: str, descriptions: list[str]) -> dict:
    """AI 生成角色（异步）"""
    from engines.llm_generator import generate_characters
    import yaml

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
    import yaml

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

    # 构建 prompt
    shots_json = json.dumps(current_shots, ensure_ascii=False, indent=2)
    prompt = f"""你是一个分镜表编辑助手。用户会用自然语言描述对分镜表的修改需求。
当前分镜表（JSON 格式）：
{shots_json}

用户指令：{message}

请根据用户的指令修改分镜表，返回修改后的完整分镜表 JSON 数组。
只返回 JSON 数组，不要其他文字。确保所有字段都保留。
如果用户的指令不清晰或无法执行，返回一个 JSON 对象：{{"error": "原因说明"}}"""

    try:
        response = llm.chat(prompt)
        # 尝试解析 JSON
        text = response.strip()
        # 去掉可能的 markdown 代码块
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        result = json.loads(text)

        if isinstance(result, dict) and "error" in result:
            return {"status": "error", "reason": result["error"]}

        if isinstance(result, list):
            self.update_state(state="PROGRESS", meta={"step": "chat_edit", "progress": 90, "message": "编辑完成"})
            return {"status": "done", "shots": result, "message": f"已修改 {len(result)} 个镜头"}

        return {"status": "error", "reason": "LLM 返回格式不正确"}

    except json.JSONDecodeError:
        return {"status": "error", "reason": "LLM 返回的不是有效 JSON"}
    except Exception as e:
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
    import yaml

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
    if import_storyboard:
        self.update_state(state="PROGRESS", meta={"step": "seko_import", "progress": 50, "message": "解析分镜..."})
        shots = _parse_seko_storyboard(steps, episode)
        if shots:
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
    # 构建 elementName → entity_id 映射（复用已解析的角色/场景 ID，避免命名不一致）
    _char_id_map: dict[str, str] = {}
    _scene_id_map: dict[str, str] = {}
    if import_characters:
        for c in chars:
            _char_id_map[c["name"]] = c["id"]
    if import_scenes:
        for s in scenes:
            _scene_id_map[s["name"]] = s["id"]

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
                    entity_id = "".join(c for c in name if c.isalnum() or c in ("-", "_")).strip() or f"char_{idx + 1:02d}"
                img_dir = project_dir / "assets" / "characters" / entity_id
                yaml_path = project_dir / "config" / "characters" / f"{entity_id}.yaml"
                asset_type = "characters"
                entity_key = "character"
            elif elem_type == "SCENE":
                entity_id = _scene_id_map.get(name)
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

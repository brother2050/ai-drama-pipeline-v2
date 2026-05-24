"""Celery 任务定义 — 每步独立，按需执行"""
from __future__ import annotations

import csv
import logging
import sys
import time
from pathlib import Path

from pipeline.celery_app import app

logger = logging.getLogger(__name__)


def _ensure_path():
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _load_shots(config_path: str, episode: int) -> list[dict]:
    sb = Path(config_path).resolve().parent.parent / "storyboard" / "episodes.csv"
    if not sb.exists():
        return []
    with open(sb, encoding="utf-8") as f:
        return [dict(r) for r in csv.DictReader(f) if int(r.get("episode", 0)) == episode]


def _find_shot(config_path: str, episode: int, shot_id: str) -> dict | None:
    sb = Path(config_path).resolve().parent.parent / "storyboard" / "episodes.csv"
    if not sb.exists():
        return None
    with open(sb, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if int(r.get("episode", 0)) == episode and r.get("shot_id") == shot_id:
                return dict(r)
    return None


def _shot_dir(config_path: str, episode: int, shot_id: str) -> Path:
    from infra.config import Config
    return Path(Config(config_path).project_dir) / "output" / f"e{episode:02d}" / f"s{shot_id}"


def _check_available(tool_name: str, config_path: str) -> tuple[bool, str]:
    from infra.config import Config
    from web.routers.api import _check_tool
    result = _check_tool(tool_name, Config(config_path).data)
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
    except Exception:
        pass


def _try_mark_running_atomic(config_path: str, episode: int, shot_id: str, step: str) -> bool:
    """原子操作：检查步骤是否正在运行，如果没有则标记为 running。

    使用 INSERT ON CONFLICT 实现原子性，避免竞态条件。
    Returns True if successfully marked (i.e., no race), False if already running.
    """
    try:
        from infra.database.pool import get_pool, placeholder
        pool = get_pool()
        conn = pool.connect()
        try:
            cur = conn.cursor()
            # 先尝试插入 running 状态，如果已存在则检查当前状态
            cur.execute(f"""
                INSERT INTO generation_status (episode, shot_id, stage, status, updated_at)
                VALUES ({placeholder()}, {placeholder()}, {placeholder()}, 'running', CURRENT_TIMESTAMP)
                ON CONFLICT (episode, shot_id, stage) DO UPDATE SET
                    status = CASE
                        WHEN generation_status.status = 'running' THEN generation_status.status
                        ELSE 'running'
                    END,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING status
            """, (episode, shot_id, step))
            row = cur.fetchone()
            conn.commit()
            # 如果返回的 status 是 running，可能是我们刚标记的，也可能是之前就在运行
            # 再查一次 updated_at 来判断：如果 updated_at 是刚更新的（<1秒），说明是我们标记的
            status = row[0] if row else "running"
            if status == "running":
                # 检查是否是旧的 running（超过 10 分钟视为超时，允许重新执行）
                cur.execute(f"""
                    SELECT EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - updated_at))
                    FROM generation_status
                    WHERE episode = {placeholder()} AND shot_id = {placeholder()} AND stage = {placeholder()}
                """, (episode, shot_id, step))
                age_row = cur.fetchone()
                age = age_row[0] if age_row else 0
                if age is not None and age > 600:  # 10 分钟超时
                    # 超时的 running 状态，允许重新执行
                    cur.execute(f"""
                        UPDATE generation_status SET status = 'running', updated_at = CURRENT_TIMESTAMP
                        WHERE episode = {placeholder()} AND shot_id = {placeholder()} AND stage = {placeholder()}
                    """, (episode, shot_id, step))
                    conn.commit()
                    return True
                # 新插入的或仍在运行的
                # 用 updated_at 判断是否是本次插入
                if age is not None and age < 2:
                    return True  # 我们刚标记的
                return False  # 别的 worker 在跑
            return True  # 不是 running，已切换为 running
        finally:
            pool.release(conn)
    except Exception:
        # 数据库不可用时回退到非原子版本
        if _check_step_running(config_path, episode, shot_id, step):
            return False
        _db_mark_running(config_path, episode, shot_id, step)
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
        return None, None, None, _skip(shot_id, step, f"{tool} 不可用: {reason}")
    shot = _find_shot(config_path, episode, shot_id) if need_shot else None
    if need_shot and not shot:
        return None, None, None, _err(shot_id, step, "镜头不存在")
    from infra.config import Config
    from api.registry import Container
    from api import _ensure_registered; _ensure_registered()
    cfg = Config(config_path)
    return cfg, Container(cfg.data), shot, None


def _skip(shot_id, step, reason): return {"shot_id": shot_id, "step": step, "status": "skipped", "reason": reason}
def _err(shot_id, step, reason): return {"shot_id": shot_id, "step": step, "status": "error", "reason": reason}
def _done(shot_id, step, path, **kw): return {"shot_id": shot_id, "step": step, "status": "done", "path": path, **kw}


# ══════════════════════════════════════════════════════════
#  核心逻辑函数
# ══════════════════════════════════════════════════════════

def _run_tts(config_path: str, episode: int, shot_id: str) -> dict:
    cfg, cont, shot, err = _prepare(config_path, episode, shot_id, "tts", "tts")
    if err:
        return err

    dialogue = shot.get("dialogue", "").strip()
    if not dialogue or dialogue == "......":
        return _skip(shot_id, "tts", "无台词")

    out_dir = _shot_dir(config_path, episode, shot_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    audio_path = str(out_dir / "audio.wav")

    char_ids = [c.strip() for c in shot.get("characters", "").split("+") if c.strip()]
    from engines.shot_manager import ShotManager
    sm = ShotManager(str(Path(cfg.project_dir) / "storyboard" / "episodes.csv"),
                     str(Path(cfg.project_dir) / "config"))
    voice_config = sm.get_character(char_ids[0]).get("voice", {}) if char_ids else {}

    try:
        cont.get("tts").synthesize(dialogue, audio_path, voice_config=voice_config)
    except Exception as e:
        return _err(shot_id, "tts", f"TTS 合成失败: {e}")
    return _done(shot_id, "tts", audio_path)


def _run_first_frame(config_path: str, episode: int, shot_id: str) -> dict:
    cfg, cont, shot, err = _prepare(config_path, episode, shot_id, "first_frame", "comfyui")
    if err:
        return err

    out_dir = _shot_dir(config_path, episode, shot_id)
    out_dir.mkdir(parents=True, exist_ok=True)

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
    Path(files[0]).rename(frame_path)
    return _done(shot_id, "first_frame", frame_path, prompt=prompt.get("positive", ""))


def _run_video(config_path: str, episode: int, shot_id: str) -> dict:
    cfg, cont, _, err = _prepare(config_path, episode, shot_id, "video", "comfyui", need_shot=False)
    if err:
        return err

    out_dir = _shot_dir(config_path, episode, shot_id)
    frame_path = out_dir / "frame.png"
    if not frame_path.exists():
        return _skip(shot_id, "video", "首帧不存在，请先执行 Step 2")

    from engines.workflow_builder import WorkflowBuilder
    wb = WorkflowBuilder(cfg.data, cfg.get("models", {}), cfg.project_dir, comfyui=cont.get("image"))
    wb.load_workflows()
    video_wf = wb.build_video(str(frame_path))
    if not video_wf:
        return _err(shot_id, "video", "视频工作流为空（缺少模板）")

    try:
        files = cont.get("video").generate(video_wf, str(out_dir))
    except Exception as e:
        return _err(shot_id, "video", f"视频生成失败: {e}")

    if not files:
        return _err(shot_id, "video", "ComfyUI 未返回任何视频")
    video_path = str(out_dir / "video.mp4")
    Path(files[0]).rename(video_path)
    return _done(shot_id, "video", video_path)


def _run_lipsync(config_path: str, episode: int, shot_id: str) -> dict:
    cfg, cont, _, err = _prepare(config_path, episode, shot_id, "lipsync", "lipsync", need_shot=False)
    if err:
        return err

    out_dir = _shot_dir(config_path, episode, shot_id)
    video_path, audio_path = out_dir / "video.mp4", out_dir / "audio.wav"
    if not video_path.exists():
        return _skip(shot_id, "lipsync", "视频不存在，请先执行 Step 3")
    if not audio_path.exists():
        return _skip(shot_id, "lipsync", "音频不存在，请先执行 Step 1")

    synced_path = str(out_dir / "synced.mp4")
    try:
        cont.get("lipsync").sync(str(video_path), str(audio_path), synced_path)
    except Exception as e:
        return _err(shot_id, "lipsync", f"口型同步失败: {e}")
    return _done(shot_id, "lipsync", synced_path)


# ══════════════════════════════════════════════════════════
#  Celery 任务包装
# ══════════════════════════════════════════════════════════

def _step_task(self, step: str, fn, config_path: str, episode: int, shot_id: str):
    """通用 Celery 步骤任务包装"""
    self.update_state(state="PROGRESS", meta={"step": step, "shot_id": shot_id, "progress": 20, "message": f"[{shot_id}] {step}..."})
    result = fn(config_path, episode, shot_id)
    if result.get("status") == "done":
        self.update_state(state="PROGRESS", meta={"step": step, "shot_id": shot_id, "progress": 100, "message": f"[{shot_id}] {step} 完成"})
    return result


@app.task(bind=True, name="pipeline.step.tts", soft_time_limit=120)
def step_tts(self, config_path, episode, shot_id): return _step_task(self, "tts", _run_tts, config_path, episode, shot_id)

@app.task(bind=True, name="pipeline.step.first_frame", soft_time_limit=300)
def step_first_frame(self, config_path, episode, shot_id): return _step_task(self, "first_frame", _run_first_frame, config_path, episode, shot_id)

@app.task(bind=True, name="pipeline.step.video", soft_time_limit=600)
def step_video(self, config_path, episode, shot_id): return _step_task(self, "video", _run_video, config_path, episode, shot_id)

@app.task(bind=True, name="pipeline.step.lipsync", soft_time_limit=300)
def step_lipsync(self, config_path, episode, shot_id): return _step_task(self, "lipsync", _run_lipsync, config_path, episode, shot_id)


# ══════════════════════════════════════════════════════════
#  编排器
# ══════════════════════════════════════════════════════════

@app.task(bind=True, name="pipeline.shot", soft_time_limit=1800)
def shot_task(self, config_path: str, episode: int, shot_data: dict):
    shot_id = shot_data.get("shot_id", "001")
    steps = [("tts", _run_tts), ("first_frame", _run_first_frame), ("video", _run_video), ("lipsync", _run_lipsync)]
    results = {}
    for i, (name, fn) in enumerate(steps):
        self.update_state(state="PROGRESS", meta={"step": name, "shot_id": shot_id, "progress": int((i + 1) / len(steps) * 100), "message": f"[{shot_id}] {name} ({i+1}/{len(steps)})"})
        try:
            t0 = time.time()
            result = fn(config_path, episode, shot_id)
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

def _iterate_shots(self, config_path: str, episode: int, shots: list[dict], progress_base: int = 0, progress_range: int = 100):
    """逐镜头执行 shot_task，返回结果列表"""
    total = len(shots)
    results = []
    for i, shot in enumerate(shots):
        shot_id = shot.get("shot_id", f"{i+1:03d}")
        self.update_state(state="PROGRESS", meta={"step": "shot", "shot_id": shot_id,
            "progress": int(progress_base + i / total * progress_range), "current": i + 1, "total": total,
            "message": f"[{i+1}/{total}] 镜头 {shot_id}"})
        try:
            results.append(shot_task.apply(args=[config_path, episode, shot]).get())
        except Exception as e:
            results.append({"shot_id": shot_id, "error": str(e)})
    return results


@app.task(bind=True, name="pipeline.preview", soft_time_limit=1800)
def preview_task(self, config_path: str, episode: int, preset: str = "draft"):
    _ensure_path()
    shots = _load_shots(config_path, episode)
    if not shots:
        return {"status": "empty", "message": f"第{episode}集没有镜头"}
    return {"status": "done", "episode": episode, "preset": preset,
            "shots": _iterate_shots(self, config_path, episode, shots)}


@app.task(bind=True, name="pipeline.produce", soft_time_limit=7200)
def produce_task(self, config_path: str, episode: int, vertical: bool = False):
    _ensure_path()
    shots = _load_shots(config_path, episode)
    if not shots:
        return {"status": "empty", "message": f"第{episode}集没有镜头"}
    try:
        self.update_state(state="PROGRESS", meta={"step": "subtitle", "progress": 2, "message": "生成字幕..."})
        _run_subtitle(config_path, episode)
    except Exception as e:
        logger.warning(f"字幕失败: {e}")
    results = _iterate_shots(self, config_path, episode, shots, progress_base=5, progress_range=80)
    self.update_state(state="PROGRESS", meta={"step": "post", "progress": 90, "message": "后期合成..."})
    try:
        _run_post(config_path, episode, vertical)
    except Exception as e:
        logger.error(f"后期失败: {e}")
    return {"status": "done", "episode": episode, "shots": results}


@app.task(bind=True, name="pipeline.post", soft_time_limit=1200)
def post_task(self, config_path: str, episode: int, vertical: bool = False):
    _ensure_path()
    self.update_state(state="PROGRESS", meta={"step": "post", "progress": 10})
    try:
        _run_post(config_path, episode, vertical)
    except Exception as e:
        logger.error(f"后期合成失败: {e}")
        return {"status": "error", "episode": episode, "reason": str(e)}
    return {"status": "done", "episode": episode, "vertical": vertical}


@app.task(bind=True, name="pipeline.portraits", soft_time_limit=1800)
def portraits_task(self, config_path: str):
    _ensure_path()
    self.update_state(state="PROGRESS", meta={"step": "portraits", "progress": 10})
    try:
        from pipeline.portraits import run_portraits
        run_portraits(config_path)
    except Exception as e:
        logger.error(f"定妆照生成失败: {e}")
        return {"status": "error", "reason": str(e)}
    return {"status": "done"}


# ══════════════════════════════════════════════════════════
#  独立工具任务
# ══════════════════════════════════════════════════════════

def _run_subtitle(config_path: str, episode: int) -> dict:
    _ensure_path()
    from post.subtitle import generate_srt
    from infra.config import Config
    cfg = Config(config_path)
    sb = Path(cfg.project_dir) / "storyboard" / "episodes.csv"
    if not sb.exists():
        return {"error": "分镜表不存在"}
    with open(sb, encoding="utf-8") as f:
        shots = [dict(r) for r in csv.DictReader(f) if int(r.get("episode", 0)) == episode]
    if not shots:
        return {"error": f"第{episode}集没有镜头"}
    out_dir = Path(cfg.project_dir) / "output" / f"e{episode:02d}"
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
    _ensure_path()
    from infra.config import Config
    from api.registry import Container
    from api import _ensure_registered; _ensure_registered()
    cfg = Config(config_path)
    cont = Container(cfg.data)
    self.update_state(state="PROGRESS", meta={"step": "tts", "progress": 20, "message": "TTS..."})
    import tempfile
    output = None
    result = None
    with tempfile.NamedTemporaryFile(suffix=".wav", prefix="tts_", delete=False) as tmp_f:
        output = tmp_f.name
    try:
        result = cont.get("tts").synthesize(text, output, voice_config=voice_config or {}, emotion=emotion, language=language)
        return {"path": result, "text": text}
    except Exception as e:
        return {"status": "error", "reason": f"TTS 合成失败: {e}", "text": text}
    finally:
        # 清理临时文件（如果结果路径不是临时文件本身）
        if output and os.path.exists(output) and result != output:
            try:
                os.unlink(output)
            except OSError:
                pass


@app.task(bind=True, name="pipeline.music", soft_time_limit=120)
def music_task(self, config_path: str, duration: float, mood: str, output: str):
    _ensure_path()
    from post.music import MusicGenerator
    from infra.config import Config
    cfg = Config(config_path)
    gen = MusicGenerator(backend=cfg.get("models", {}).get("music_backend", "template"), config=cfg.data)
    try:
        result = gen.generate(duration, output, mood=mood)
    except Exception as e:
        return {"status": "error", "reason": f"配乐生成失败: {e}", "mood": mood, "duration": duration}
    return {"path": result, "mood": mood, "duration": duration}


@app.task(bind=True, name="pipeline.subtitle", soft_time_limit=60)
def subtitle_task(self, config_path: str, episode: int):
    return _run_subtitle(config_path, episode)

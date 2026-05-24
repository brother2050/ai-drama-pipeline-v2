"""Celery 任务定义 — 所有异步管线任务

每个任务通过 self.update_state() 报告进度，前端轮询 /api/tasks/{id} 获取状态。
"""
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
    """加载分镜表"""
    cfg_dir = Path(config_path).resolve().parent.parent
    sb_path = cfg_dir / "storyboard" / "episodes.csv"
    if not sb_path.exists():
        return []
    shots = []
    with open(sb_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if int(row.get("episode", 0)) == episode:
                shots.append(row)
    return shots


# ── 单步任务（可被 shot_task 编排调用） ──

@app.task(bind=True, name="pipeline.tts", soft_time_limit=120)
def tts_task(self, config_path: str, episode: int, shot_id: str,
             text: str, voice_config: dict | None = None, output: str = ""):
    """TTS 语音合成"""
    _ensure_path()
    from infra.config import Config
    from api.registry import Container
    import api  # noqa: F401 触发自注册

    cfg = Config(config_path)
    cont = Container(cfg.data)
    tts = cont.get("tts")

    self.update_state(state="PROGRESS", meta={"stage": "tts", "shot_id": shot_id, "progress": 10})
    result = tts.synthesize(text, output, voice_config=voice_config or {})
    return {"shot_id": shot_id, "stage": "tts", "path": result}


@app.task(bind=True, name="pipeline.first_frame", soft_time_limit=300)
def first_frame_task(self, config_path: str, episode: int, shot_id: str,
                     prompt: str, output_dir: str):
    """首帧图片生成"""
    _ensure_path()
    from infra.config import Config
    from api.registry import Container
    import api  # noqa: F401

    cfg = Config(config_path)
    cont = Container(cfg.data)

    self.update_state(state="PROGRESS", meta={"stage": "first_frame", "shot_id": shot_id, "progress": 20})
    comfyui = cont.get("image")
    files = comfyui.generate({"prompt": {"positive": prompt}}, output_dir)
    return {"shot_id": shot_id, "stage": "first_frame", "files": files}


@app.task(bind=True, name="pipeline.video_gen", soft_time_limit=600)
def video_gen_task(self, config_path: str, episode: int, shot_id: str,
                   workflow: dict, output_dir: str):
    """视频生成"""
    _ensure_path()
    from infra.config import Config
    from api.registry import Container
    import api  # noqa: F401

    cfg = Config(config_path)
    cont = Container(cfg.data)

    self.update_state(state="PROGRESS", meta={"stage": "video", "shot_id": shot_id, "progress": 40})
    video_backend = cont.get("video")
    files = video_backend.generate(workflow, output_dir)
    return {"shot_id": shot_id, "stage": "video", "files": files}


@app.task(bind=True, name="pipeline.lipsync", soft_time_limit=300)
def lipsync_task(self, config_path: str, episode: int, shot_id: str,
                 video_path: str, audio_path: str, output: str):
    """口型同步"""
    _ensure_path()
    from infra.config import Config
    from api.registry import Container
    import api  # noqa: F401

    cfg = Config(config_path)
    cont = Container(cfg.data)

    self.update_state(state="PROGRESS", meta={"stage": "lipsync", "shot_id": shot_id, "progress": 70})
    lipsync = cont.get("lipsync")
    result = lipsync.sync(video_path, audio_path, output)
    return {"shot_id": shot_id, "stage": "lipsync", "path": result}


# ── 单镜头全流程 ──

@app.task(bind=True, name="pipeline.shot", soft_time_limit=1800)
def shot_task(self, config_path: str, episode: int, shot_data: dict):
    """单镜头全流程：TTS → 首帧 → 视频 → 口型同步"""
    _ensure_path()
    from infra.config import Config
    from api.registry import Container
    from engines.prompt import build_prompt, translate_to_english
    from engines.shot_manager import ShotManager
    import api  # noqa: F401

    shot_id = shot_data.get("shot_id", "001")
    cfg = Config(config_path)
    cont = Container(cfg.data)
    out_dir = Path(cfg.project_dir) / "output" / f"e{episode:02d}" / f"s{shot_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    char_ids = [c.strip() for c in shot_data.get("characters", "").split("+") if c.strip()]
    dialogue = shot_data.get("dialogue", "").strip()

    # ── 1. TTS ──
    audio_path = str(out_dir / "audio.wav")
    if dialogue and dialogue != "......":
        try:
            self.update_state(state="PROGRESS", meta={
                "stage": "tts", "shot_id": shot_id, "progress": 5,
                "message": f"[{shot_id}] TTS 合成中..."})
            tts = cont.get("tts")
            sm = ShotManager("", str(Path(cfg.project_dir) / "config"))
            char = sm.get_character(char_ids[0]) if char_ids else {}
            tts.synthesize(dialogue, audio_path, voice_config=char.get("voice", {}))
        except Exception as e:
            logger.error(f"[{shot_id}] TTS 失败: {e}")

    # ── 2. 首帧 ──
    frame_path = str(out_dir / "frame.png")
    try:
        self.update_state(state="PROGRESS", meta={
            "stage": "first_frame", "shot_id": shot_id, "progress": 25,
            "message": f"[{shot_id}] 首帧生成中..."})
        sm = ShotManager("", str(Path(cfg.project_dir) / "config"))
        char_descs = []
        for cid in char_ids:
            c = sm.get_character(cid)
            if c:
                char_descs.append(translate_to_english(c.get("appearance", "")))
        scene = sm.get_scene(shot_data.get("scene", ""))
        scene_desc = translate_to_english(scene.get("description", "")) if scene else ""
        action_en = translate_to_english(shot_data.get("action", ""))

        prompt = build_prompt({**shot_data, "action_en": action_en},
                              character_desc=", ".join(char_descs),
                              scene_desc=scene_desc,
                              style=cfg.get("project.style", "cinematic"),
                              genre=cfg.get("project.genre", "urban"))
        comfyui = cont.get("image")
        files = comfyui.generate({"prompt": {"positive": prompt}}, str(out_dir))
        if files:
            Path(files[0]).rename(frame_path)
    except Exception as e:
        logger.error(f"[{shot_id}] 首帧失败: {e}")

    # ── 3. 视频 ──
    video_path = str(out_dir / "video.mp4")
    if Path(frame_path).exists():
        try:
            self.update_state(state="PROGRESS", meta={
                "stage": "video", "shot_id": shot_id, "progress": 45,
                "message": f"[{shot_id}] 视频生成中..."})
            from engines.workflow_builder import WorkflowBuilder
            models = cfg.get("models", {})
            wb = WorkflowBuilder(cfg.data, models, cfg.project_dir)
            wb.load_workflows()
            video_wf = wb.build_video(frame_path)
            if video_wf:
                video_backend = cont.get("video")
                files = video_backend.generate(video_wf, str(out_dir))
                if files:
                    Path(files[0]).rename(video_path)
        except Exception as e:
            logger.error(f"[{shot_id}] 视频失败: {e}")

    # ── 4. 口型同步 ──
    synced_path = str(out_dir / "synced.mp4")
    if Path(video_path).exists() and Path(audio_path).exists():
        try:
            self.update_state(state="PROGRESS", meta={
                "stage": "lipsync", "shot_id": shot_id, "progress": 75,
                "message": f"[{shot_id}] 口型同步中..."})
            lipsync = cont.get("lipsync")
            lipsync.sync(video_path, audio_path, synced_path)
        except Exception as e:
            logger.error(f"[{shot_id}] 口型同步失败: {e}")

    self.update_state(state="PROGRESS", meta={
        "stage": "done", "shot_id": shot_id, "progress": 100,
        "message": f"[{shot_id}] 完成"})

    return {
        "shot_id": shot_id,
        "audio": audio_path if Path(audio_path).exists() else None,
        "frame": frame_path if Path(frame_path).exists() else None,
        "video": video_path if Path(video_path).exists() else None,
        "synced": synced_path if Path(synced_path).exists() else None,
    }


# ── 集级任务（编排所有镜头） ──

@app.task(bind=True, name="pipeline.preview", soft_time_limit=1800)
def preview_task(self, config_path: str, episode: int, preset: str = "draft"):
    """快速预览 — 串行执行所有镜头"""
    _ensure_path()
    shots = _load_shots(config_path, episode)
    if not shots:
        return {"status": "empty", "message": f"第{episode}集没有镜头"}

    total = len(shots)
    results = []
    for i, shot in enumerate(shots):
        shot_id = shot.get("shot_id", f"{i+1:03d}")
        self.update_state(state="PROGRESS", meta={
            "stage": "shot", "shot_id": shot_id,
            "progress": int(i / total * 100),
            "current": i + 1, "total": total,
            "message": f"预览 [{i+1}/{total}] 镜头 {shot_id}"})
        try:
            result = shot_task.apply(args=[config_path, episode, shot]).get()
            results.append(result)
        except Exception as e:
            results.append({"shot_id": shot_id, "error": str(e)})

    return {"status": "done", "episode": episode, "preset": preset, "shots": results}


@app.task(bind=True, name="pipeline.produce", soft_time_limit=7200)
def produce_task(self, config_path: str, episode: int):
    """完整生产 — 串行执行镜头 + 后期合成"""
    _ensure_path()
    shots = _load_shots(config_path, episode)
    if not shots:
        return {"status": "empty", "message": f"第{episode}集没有镜头"}

    total = len(shots)
    results = []

    # 生成字幕
    try:
        from post.subtitle import generate_srt
        cfg_dir = Path(config_path).resolve().parent.parent
        out_dir = cfg_dir / "output" / f"e{episode:02d}"
        out_dir.mkdir(parents=True, exist_ok=True)
        srt_path = out_dir / f"episode_{episode:02d}.srt"
        generate_srt(shots, str(srt_path))
    except Exception as e:
        logger.warning(f"字幕生成失败: {e}")

    # 逐镜头处理
    for i, shot in enumerate(shots):
        shot_id = shot.get("shot_id", f"{i+1:03d}")
        self.update_state(state="PROGRESS", meta={
            "stage": "shot", "shot_id": shot_id,
            "progress": int(i / total * 80),
            "current": i + 1, "total": total,
            "message": f"生产 [{i+1}/{total}] 镜头 {shot_id}"})
        try:
            result = shot_task.apply(args=[config_path, episode, shot]).get()
            results.append(result)
        except Exception as e:
            results.append({"shot_id": shot_id, "error": str(e)})

    # 后期合成
    self.update_state(state="PROGRESS", meta={
        "stage": "post", "progress": 85,
        "message": "后期合成中..."})
    try:
        from post.production import run_post
        run_post(config_path, episode)
    except Exception as e:
        logger.error(f"后期合成失败: {e}")

    self.update_state(state="PROGRESS", meta={
        "stage": "done", "progress": 100,
        "message": "完成"})

    return {"status": "done", "episode": episode, "shots": results}


@app.task(bind=True, name="pipeline.post", soft_time_limit=1200)
def post_task(self, config_path: str, episode: int, vertical: bool = False):
    """后期合成"""
    _ensure_path()
    self.update_state(state="PROGRESS", meta={"stage": "post", "progress": 10})
    from post.production import run_post
    run_post(config_path, episode, vertical)
    return {"status": "done", "episode": episode, "vertical": vertical}


@app.task(bind=True, name="pipeline.portraits", soft_time_limit=1800)
def portraits_task(self, config_path: str):
    """定妆照生成"""
    _ensure_path()
    self.update_state(state="PROGRESS", meta={"stage": "portraits", "progress": 10})
    from pipeline.portraits import run_portraits
    run_portraits(config_path)
    return {"status": "done"}

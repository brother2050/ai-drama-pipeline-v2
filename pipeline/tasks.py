"""Celery 任务定义 — 每步独立，按需执行

设计原则：
- 每步是独立的 Celery 任务，只依赖自己需要的工具
- 每步完成后保存结果到磁盘，下一步从磁盘读取
- 缺工具 = 跳过该步，不报错，不影响其他步
- 前端可按步调用，也可以一键编排全部
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


def _find_shot(config_path: str, episode: int, shot_id: str) -> dict | None:
    cfg_dir = Path(config_path).resolve().parent.parent
    sb_path = cfg_dir / "storyboard" / "episodes.csv"
    if not sb_path.exists():
        return None
    with open(sb_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if int(row.get("episode", 0)) == episode and row.get("shot_id") == shot_id:
                return dict(row)
    return None


def _shot_dir(config_path: str, episode: int, shot_id: str) -> Path:
    from infra.config import Config
    cfg = Config(config_path)
    return Path(cfg.project_dir) / "output" / f"e{episode:02d}" / f"s{shot_id}"


def _check_available(tool_name: str, config_path: str) -> tuple[bool, str]:
    """检测工具是否可用"""
    from infra.config import Config
    cfg = Config(config_path)
    from web.routers.api import _check_tool
    result = _check_tool(tool_name, cfg.data)
    return result["available"], result.get("reason", "")


# ══════════════════════════════════════════════════════════
#  Step 1: TTS 语音合成 — 只需要 TTS 服务
# ══════════════════════════════════════════════════════════

@app.task(bind=True, name="pipeline.step.tts", soft_time_limit=120)
def step_tts(self, config_path: str, episode: int, shot_id: str):
    """Step 1: TTS — 将台词合成为音频"""
    _ensure_path()

    # 检测工具
    ok, reason = _check_available("tts", config_path)
    if not ok:
        return {"shot_id": shot_id, "step": "tts", "status": "skipped", "reason": f"TTS 不可用: {reason}"}

    shot = _find_shot(config_path, episode, shot_id)
    if not shot:
        return {"shot_id": shot_id, "step": "tts", "status": "error", "reason": "镜头不存在"}

    dialogue = shot.get("dialogue", "").strip()
    if not dialogue or dialogue == "......":
        return {"shot_id": shot_id, "step": "tts", "status": "skipped", "reason": "无台词"}

    self.update_state(state="PROGRESS", meta={
        "step": "tts", "shot_id": shot_id, "progress": 20,
        "message": f"[{shot_id}] TTS: {dialogue[:20]}..."})

    from infra.config import Config
    from api.registry import Container
    import api  # noqa: F401

    cfg = Config(config_path)
    cont = Container(cfg.data)
    out_dir = _shot_dir(config_path, episode, shot_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    audio_path = str(out_dir / "audio.wav")
    tts = cont.get("tts")

    # 获取角色语音配置
    char_ids = [c.strip() for c in shot.get("characters", "").split("+") if c.strip()]
    from engines.shot_manager import ShotManager
    sm = ShotManager("", str(Path(cfg.project_dir) / "config"))
    char = sm.get_character(char_ids[0]) if char_ids else {}
    voice_config = char.get("voice", {})

    tts.synthesize(dialogue, audio_path, voice_config=voice_config)

    self.update_state(state="PROGRESS", meta={
        "step": "tts", "shot_id": shot_id, "progress": 100, "message": f"[{shot_id}] TTS 完成"})
    return {"shot_id": shot_id, "step": "tts", "status": "done", "path": audio_path}


# ══════════════════════════════════════════════════════════
#  Step 2: 首帧生成 — 只需要 ComfyUI
# ══════════════════════════════════════════════════════════

@app.task(bind=True, name="pipeline.step.first_frame", soft_time_limit=300)
def step_first_frame(self, config_path: str, episode: int, shot_id: str):
    """Step 2: 首帧 — 生成镜头第一帧图片"""
    _ensure_path()

    ok, reason = _check_available("comfyui", config_path)
    if not ok:
        return {"shot_id": shot_id, "step": "first_frame", "status": "skipped",
                "reason": f"ComfyUI 不可用: {reason}"}

    shot = _find_shot(config_path, episode, shot_id)
    if not shot:
        return {"shot_id": shot_id, "step": "first_frame", "status": "error", "reason": "镜头不存在"}

    self.update_state(state="PROGRESS", meta={
        "step": "first_frame", "shot_id": shot_id, "progress": 20,
        "message": f"[{shot_id}] 首帧生成中..."})

    from infra.config import Config
    from api.registry import Container
    from engines.prompt import build_prompt, translate_to_english
    from engines.shot_manager import ShotManager
    import api  # noqa: F401

    cfg = Config(config_path)
    cont = Container(cfg.data)
    out_dir = _shot_dir(config_path, episode, shot_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 构建 prompt
    char_ids = [c.strip() for c in shot.get("characters", "").split("+") if c.strip()]
    sm = ShotManager("", str(Path(cfg.project_dir) / "config"))
    char_descs = []
    for cid in char_ids:
        c = sm.get_character(cid)
        if c:
            char_descs.append(translate_to_english(c.get("appearance", "")))
    scene = sm.get_scene(shot.get("scene", ""))
    scene_desc = translate_to_english(scene.get("description", "")) if scene else ""
    action_en = translate_to_english(shot.get("action", ""))

    prompt = build_prompt({**shot, "action_en": action_en},
                          character_desc=", ".join(char_descs),
                          scene_desc=scene_desc,
                          style=cfg.get("project.style", "cinematic"),
                          genre=cfg.get("project.genre", "urban"))

    comfyui = cont.get("image")
    files = comfyui.generate({"prompt": {"positive": prompt}}, str(out_dir))
    frame_path = str(out_dir / "frame.png")
    if files:
        Path(files[0]).rename(frame_path)

    self.update_state(state="PROGRESS", meta={
        "step": "first_frame", "shot_id": shot_id, "progress": 100,
        "message": f"[{shot_id}] 首帧完成"})
    return {"shot_id": shot_id, "step": "first_frame", "status": "done",
            "path": frame_path, "prompt": prompt}


# ══════════════════════════════════════════════════════════
#  Step 3: 视频生成 — 只需要 ComfyUI + 首帧已存在
# ══════════════════════════════════════════════════════════

@app.task(bind=True, name="pipeline.step.video", soft_time_limit=600)
def step_video(self, config_path: str, episode: int, shot_id: str):
    """Step 3: 视频 — 从首帧生成视频片段"""
    _ensure_path()

    ok, reason = _check_available("comfyui", config_path)
    if not ok:
        return {"shot_id": shot_id, "step": "video", "status": "skipped",
                "reason": f"ComfyUI 不可用: {reason}"}

    out_dir = _shot_dir(config_path, episode, shot_id)
    frame_path = out_dir / "frame.png"
    if not frame_path.exists():
        return {"shot_id": shot_id, "step": "video", "status": "skipped",
                "reason": "首帧不存在，请先执行 Step 2"}

    self.update_state(state="PROGRESS", meta={
        "step": "video", "shot_id": shot_id, "progress": 20,
        "message": f"[{shot_id}] 视频生成中..."})

    from infra.config import Config
    from api.registry import Container
    from engines.workflow_builder import WorkflowBuilder
    import api  # noqa: F401

    cfg = Config(config_path)
    cont = Container(cfg.data)

    models = cfg.get("models", {})
    wb = WorkflowBuilder(cfg.data, models, cfg.project_dir)
    wb.load_workflows()
    video_wf = wb.build_video(str(frame_path))

    if not video_wf:
        return {"shot_id": shot_id, "step": "video", "status": "error",
                "reason": "视频工作流为空（缺少模板）"}

    video_backend = cont.get("video")
    files = video_backend.generate(video_wf, str(out_dir))
    video_path = str(out_dir / "video.mp4")
    if files:
        Path(files[0]).rename(video_path)

    self.update_state(state="PROGRESS", meta={
        "step": "video", "shot_id": shot_id, "progress": 100,
        "message": f"[{shot_id}] 视频完成"})
    return {"shot_id": shot_id, "step": "video", "status": "done", "path": video_path}


# ══════════════════════════════════════════════════════════
#  Step 4: 口型同步 — 只需要 LipSync + 视频 + 音频
# ══════════════════════════════════════════════════════════

@app.task(bind=True, name="pipeline.step.lipsync", soft_time_limit=300)
def step_lipsync(self, config_path: str, episode: int, shot_id: str):
    """Step 4: 口型同步 — 视频+音频→口型同步视频"""
    _ensure_path()

    ok, reason = _check_available("lipsync", config_path)
    if not ok:
        return {"shot_id": shot_id, "step": "lipsync", "status": "skipped",
                "reason": f"LipSync 不可用: {reason}"}

    out_dir = _shot_dir(config_path, episode, shot_id)
    video_path = out_dir / "video.mp4"
    audio_path = out_dir / "audio.wav"

    if not video_path.exists():
        return {"shot_id": shot_id, "step": "lipsync", "status": "skipped",
                "reason": "视频不存在，请先执行 Step 3"}
    if not audio_path.exists():
        return {"shot_id": shot_id, "step": "lipsync", "status": "skipped",
                "reason": "音频不存在，请先执行 Step 1"}

    self.update_state(state="PROGRESS", meta={
        "step": "lipsync", "shot_id": shot_id, "progress": 20,
        "message": f"[{shot_id}] 口型同步中..."})

    from infra.config import Config
    from api.registry import Container
    import api  # noqa: F401

    cfg = Config(config_path)
    cont = Container(cfg.data)

    lipsync = cont.get("lipsync")
    synced_path = str(out_dir / "synced.mp4")
    lipsync.sync(str(video_path), str(audio_path), synced_path)

    self.update_state(state="PROGRESS", meta={
        "step": "lipsync", "shot_id": shot_id, "progress": 100,
        "message": f"[{shot_id}] 口型同步完成"})
    return {"shot_id": shot_id, "step": "lipsync", "status": "done", "path": synced_path}


# ══════════════════════════════════════════════════════════
#  编排器 — 逐步尝试，能跑哪步跑哪步
# ══════════════════════════════════════════════════════════

@app.task(bind=True, name="pipeline.shot", soft_time_limit=1800)
def shot_task(self, config_path: str, episode: int, shot_data: dict):
    """单镜头编排：逐步尝试，跳过不可用的步骤

    不会因为缺工具而失败，只执行当前可用的步骤。
    每步在当前 Worker 线程内同步执行（子任务不需要再排队）。
    """
    shot_id = shot_data.get("shot_id", "001")
    step_fns = [
        ("tts",         step_tts),
        ("first_frame", step_first_frame),
        ("video",       step_video),
        ("lipsync",     step_lipsync),
    ]

    results = {}
    for i, (step_name, step_fn) in enumerate(step_fns):
        pct = int((i + 1) / len(step_fns) * 100)
        self.update_state(state="PROGRESS", meta={
            "step": step_name, "shot_id": shot_id,
            "progress": pct,
            "message": f"[{shot_id}] {step_name} ({i+1}/{len(step_fns)})"})

        try:
            # .apply() 在当前 Worker 进程同步执行，保持 Celery task 上下文
            # 不重新排队，不占用额外 Worker 槽位
            # 设置超时防止无限等待
            timeout_map = {"tts": 120, "first_frame": 300, "video": 600, "lipsync": 300}
            step_timeout = timeout_map.get(step_name, 300)
            result = step_fn.apply(args=[config_path, episode, shot_id]).get(timeout=step_timeout)
            results[step_name] = result

            status = result.get("status", "")
            if status == "skipped":
                logger.info(f"[{shot_id}] {step_name}: 跳过 — {result.get('reason', '')}")
            elif status == "error":
                logger.warning(f"[{shot_id}] {step_name}: 错误 — {result.get('reason', '')}")
            else:
                logger.info(f"[{shot_id}] {step_name}: 完成")

        except Exception as e:
            logger.error(f"[{shot_id}] {step_name}: 异常 — {e}")
            results[step_name] = {"status": "error", "reason": str(e)}

    # 汇总
    done = [k for k, v in results.items() if v.get("status") == "done"]
    skipped = [k for k, v in results.items() if v.get("status") == "skipped"]
    errors = [k for k, v in results.items() if v.get("status") == "error"]

    return {
        "shot_id": shot_id,
        "done": done,
        "skipped": skipped,
        "errors": errors,
        "details": results,
    }


# ══════════════════════════════════════════════════════════
#  集级任务
# ══════════════════════════════════════════════════════════

@app.task(bind=True, name="pipeline.preview", soft_time_limit=1800)
def preview_task(self, config_path: str, episode: int, preset: str = "draft"):
    """快速预览 — 逐镜头执行可用步骤"""
    _ensure_path()
    shots = _load_shots(config_path, episode)
    if not shots:
        return {"status": "empty", "message": f"第{episode}集没有镜头"}

    total = len(shots)
    results = []
    for i, shot in enumerate(shots):
        shot_id = shot.get("shot_id", f"{i+1:03d}")
        self.update_state(state="PROGRESS", meta={
            "step": "shot", "shot_id": shot_id,
            "progress": int(i / total * 100),
            "current": i + 1, "total": total,
            "message": f"[{i+1}/{total}] 镜头 {shot_id}"})
        try:
            result = shot_task.apply(args=[config_path, episode, shot]).get()
            results.append(result)
        except Exception as e:
            results.append({"shot_id": shot_id, "error": str(e)})

    return {"status": "done", "episode": episode, "preset": preset, "shots": results}


@app.task(bind=True, name="pipeline.produce", soft_time_limit=7200)
def produce_task(self, config_path: str, episode: int):
    """完整生产 — 逐镜头 + 后期"""
    _ensure_path()
    shots = _load_shots(config_path, episode)
    if not shots:
        return {"status": "empty", "message": f"第{episode}集没有镜头"}

    total = len(shots)

    # 字幕
    try:
        self.update_state(state="PROGRESS", meta={
            "step": "subtitle", "progress": 2,
            "message": "生成字幕..."})
        subtitle_task.apply(args=[config_path, episode]).get()
    except Exception as e:
        logger.warning(f"字幕失败: {e}")

    # 逐镜头
    results = []
    for i, shot in enumerate(shots):
        shot_id = shot.get("shot_id", f"{i+1:03d}")
        self.update_state(state="PROGRESS", meta={
            "step": "shot", "shot_id": shot_id,
            "progress": int(5 + i / total * 80),
            "current": i + 1, "total": total,
            "message": f"[{i+1}/{total}] 镜头 {shot_id}"})
        try:
            result = shot_task.apply(args=[config_path, episode, shot]).get()
            results.append(result)
        except Exception as e:
            results.append({"shot_id": shot_id, "error": str(e)})

    # 后期
    self.update_state(state="PROGRESS", meta={
        "step": "post", "progress": 90, "message": "后期合成..."})
    try:
        post_task.apply(args=[config_path, episode]).get()
    except Exception as e:
        logger.error(f"后期失败: {e}")

    return {"status": "done", "episode": episode, "shots": results}


@app.task(bind=True, name="pipeline.post", soft_time_limit=1200)
def post_task(self, config_path: str, episode: int, vertical: bool = False):
    """后期合成"""
    _ensure_path()
    self.update_state(state="PROGRESS", meta={"step": "post", "progress": 10})
    from post.production import run_post
    run_post(config_path, episode, vertical)
    return {"status": "done", "episode": episode, "vertical": vertical}


@app.task(bind=True, name="pipeline.portraits", soft_time_limit=1800)
def portraits_task(self, config_path: str):
    """定妆照"""
    _ensure_path()
    self.update_state(state="PROGRESS", meta={"step": "portraits", "progress": 10})
    from pipeline.portraits import run_portraits
    run_portraits(config_path)
    return {"status": "done"}


# ══════════════════════════════════════════════════════════
#  独立工具任务（直接调用，不走编排）
# ══════════════════════════════════════════════════════════

@app.task(bind=True, name="pipeline.tts_single", soft_time_limit=120)
def tts_single_task(self, config_path: str, text: str,
                    voice_config: dict | None = None,
                    emotion: str = "neutral", language: str = "zh"):
    """独立 TTS"""
    _ensure_path()
    from infra.config import Config
    from api.registry import Container
    import api  # noqa: F401

    cfg = Config(config_path)
    cont = Container(cfg.data)
    self.update_state(state="PROGRESS", meta={"step": "tts", "progress": 20, "message": "TTS..."})
    tts = cont.get("tts")

    import tempfile
    output = tempfile.mktemp(suffix=".wav", prefix="tts_")
    result = tts.synthesize(text, output, voice_config=voice_config or {},
                            emotion=emotion, language=language)
    return {"path": result, "text": text}


@app.task(bind=True, name="pipeline.music", soft_time_limit=120)
def music_task(self, config_path: str, duration: float, mood: str, output: str):
    """独立配乐"""
    _ensure_path()
    from post.music import MusicGenerator
    from infra.config import Config

    cfg = Config(config_path)
    backend = cfg.get("models", {}).get("music_backend", "template")
    gen = MusicGenerator(backend=backend, config=cfg.data)
    result = gen.generate(duration, output, mood=mood)
    return {"path": result, "mood": mood, "duration": duration}


@app.task(bind=True, name="pipeline.subtitle", soft_time_limit=60)
def subtitle_task(self, config_path: str, episode: int):
    """独立字幕"""
    _ensure_path()
    from post.subtitle import generate_srt
    from infra.config import Config

    cfg = Config(config_path)
    sb_path = Path(cfg.project_dir) / "storyboard" / "episodes.csv"
    if not sb_path.exists():
        return {"error": "分镜表不存在"}

    shots = []
    with open(sb_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if int(row.get("episode", 0)) == episode:
                shots.append(row)
    if not shots:
        return {"error": f"第{episode}集没有镜头"}

    out_dir = Path(cfg.project_dir) / "output" / f"e{episode:02d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    srt_path = str(out_dir / f"episode_{episode:02d}.srt")
    generate_srt(shots, srt_path)
    return {"path": srt_path, "count": len(shots)}

"""快速预览管线 — draft/standard/high 三档"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infra.config import Config

logger = logging.getLogger(__name__)


def run_preview(config_path: str, episode: int, level: str = "draft"):
    """快速预览"""
    cfg = Config(config_path)
    logger.info(f"预览 第{episode}集 ({level})")

    # 触发后端自注册
    from api import _ensure_registered; _ensure_registered()
    from api.registry import Container
    cont = Container(cfg.data)

    # 加载分镜
    sb_path = Path(cfg.project_dir) / "storyboard" / "episodes.csv"
    if not sb_path.exists():
        logger.warning("分镜表不存在")
        return

    shots = []
    with open(sb_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if int(row.get("episode", 0)) == episode:
                shots.append(row)

    if not shots:
        logger.warning(f"第{episode}集没有镜头")
        return

    # 预设参数
    presets = {
        "draft": {"steps": 8, "resolution": [512, 288], "video_frames": 4},
        "standard": {"steps": 20, "resolution": [768, 432], "video_frames": 8},
        "high": {"steps": 28, "resolution": [1280, 720], "video_frames": 16},
    }
    preset = presets.get(level, presets["draft"])

    out_dir = Path(cfg.project_dir) / "output" / f"e{episode:02d}"
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"共 {len(shots)} 个镜头，预设: {level}")

    # 加载角色和场景配置
    from engines.shot_manager import ShotManager
    config_dir = Path(cfg.project_dir) / "config"
    sb_path_str = str(sb_path)
    sm = ShotManager(sb_path_str, str(config_dir), cfg.data)

    # 逐镜头处理
    for shot in shots:
        sid = shot.get("shot_id", "001")
        logger.info(f"  镜头 {sid}: {shot.get('action', '')[:30]}...")

        shot_out = out_dir / f"s{sid}"
        shot_out.mkdir(parents=True, exist_ok=True)

        try:
            _process_shot(shot, sm, cont, cfg, shot_out, preset)
        except Exception as e:
            logger.error(f"  ❌ 镜头 {sid} 失败: {e}")
            continue

    logger.info("预览完成")


def _process_shot(shot: dict, sm, container, cfg, shot_out: Path, preset: dict):
    """处理单个镜头"""
    from engines.prompt import build_prompt, translate_to_english
    from engines.camera import normalize_camera, normalize_shot_type

    shot_id = shot.get("shot_id", "001")
    char_ids = [c.strip() for c in shot.get("characters", "").split("+") if c.strip()]

    # 获取角色描述
    char_descs = []
    for cid in char_ids:
        char = sm.get_character(cid)
        if char:
            desc = translate_to_english(char.get("appearance", ""), llm=None)
            char_descs.append(desc)

    # 获取场景描述
    scene_id = shot.get("scene", "")
    scene = sm.get_scene(scene_id)
    scene_desc = translate_to_english(scene.get("description", ""), llm=None) if scene else ""

    # 1) TTS 语音合成
    dialogue = shot.get("dialogue", "").strip()
    audio_path = shot_out / "audio.wav"
    if dialogue and dialogue != "......":
        try:
            tts = container.get("tts")
            char = sm.get_character(char_ids[0]) if char_ids else {}
            voice_config = char.get("voice", {})
            tts.synthesize(dialogue, str(audio_path), voice_config=voice_config)
            logger.info(f"    ✅ TTS: {audio_path.name}")
        except Exception as e:
            logger.warning(f"    ⚠ TTS 失败: {e}")

    # 2) 首帧生成（需要 ComfyUI，使用 WorkflowBuilder 含 IP-Adapter）
    frame_path = shot_out / "frame.png"
    try:
        from engines.workflow_builder import WorkflowBuilder
        from engines.multi_char import MultiCharacterHandler

        # 多角色 prompt
        multi_char_prompt = ""
        if len(char_ids) > 1:
            mch = MultiCharacterHandler()
            chars_data = [sm.get_character(cid) for cid in char_ids]
            multi_char_prompt = mch.generate_multi_char_prompt([c for c in chars_data if c])

        models = cfg.get("models", {})
        wb = WorkflowBuilder(cfg.data, models, cfg.project_dir)
        wb.load_workflows()
        prompt, wf = wb.build_first_frame(
            shot, character_desc=", ".join(char_descs),
            scene_desc=scene_desc, multi_char_prompt=multi_char_prompt)

        if wf:
            comfyui = container.get("image")
            files = comfyui.generate(wf, str(shot_out))
            if files:
                from pathlib import Path as P
                P(files[0]).rename(frame_path)
                logger.info(f"    ✅ 首帧: {frame_path.name}")
        else:
            logger.warning(f"    ⚠ 首帧工作流为空")
    except Exception as e:
        logger.warning(f"    ⚠ 首帧生成失败: {e}")

    # 3) 视频生成（需要 ComfyUI）
    video_path = shot_out / "video.mp4"
    if frame_path.exists():
        try:
            from engines.workflow_builder import WorkflowBuilder
            models = cfg.get("models", {})
            wb = WorkflowBuilder(cfg.data, models, cfg.project_dir)
            wb.load_workflows()
            video_wf = wb.build_video(str(frame_path))
            if video_wf:
                video_backend = container.get("video")
                files = video_backend.generate(video_wf, str(shot_out))
                if files:
                    from pathlib import Path as P
                    P(files[0]).rename(video_path)
                    logger.info(f"    ✅ 视频: {video_path.name}")
            else:
                logger.warning(f"    ⚠ 视频工作流为空（缺少模板）")
        except Exception as e:
            logger.warning(f"    ⚠ 视频生成失败: {e}")

    # 4) 口型同步
    if video_path.exists() and audio_path.exists():
        try:
            lipsync = container.get("lipsync")
            synced_path = shot_out / "synced.mp4"
            lipsync.sync(str(video_path), str(audio_path), str(synced_path))
            logger.info(f"    ✅ 口型同步: {synced_path.name}")
        except Exception as e:
            logger.warning(f"    ⚠ 口型同步失败: {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", required=True)
    parser.add_argument("-e", "--episode", type=int, default=1)
    parser.add_argument("-p", "--preset", default="draft",
                        choices=["draft", "standard", "high"])
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_preview(args.config, args.episode, args.preset)


if __name__ == "__main__":
    main()

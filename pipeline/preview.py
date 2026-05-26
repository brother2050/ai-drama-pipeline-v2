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
            try:
                ep = int(row.get("episode", 0) or 0)
            except (ValueError, TypeError):
                continue
            if ep == episode:
                shots.append(row)

    if not shots:
        logger.warning(f"第{episode}集没有镜头")
        return

    # 预设参数 — 基于 generation config，按质量档位缩放
    from infra.gpu import get_generation_config
    gen = get_generation_config(cfg)
    base_steps = gen.get("image_steps", 20)
    base_res = gen.get("resolution", [512, 512])
    base_frames = gen.get("video_frames", 8)

    presets = {
        "draft": {"steps": max(4, base_steps // 3), "resolution": [max(256, base_res[0] // 2), max(144, base_res[1] // 2)], "video_frames": max(4, base_frames // 2)},
        "standard": {"steps": base_steps, "resolution": base_res, "video_frames": base_frames},
        "high": {"steps": int(base_steps * 1.4), "resolution": [min(1920, int(base_res[0] * 1.5)), min(1080, int(base_res[1] * 1.5))], "video_frames": min(16, int(base_frames * 2))},
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

    shot_id = shot.get("shot_id", "001")
    char_ids = [c.strip() for c in shot.get("characters", "").split("+") if c.strip()]

    # 获取 LLM 后端用于翻译（可选）
    llm = None
    try:
        if cfg.get("llm", {}).get("enabled"):
            llm = container.get("llm")
    except Exception:
        pass

    # 获取角色描述
    char_descs = []
    for cid in char_ids:
        char = sm.get_character(cid)
        if char:
            desc = translate_to_english(char.get("appearance", ""), llm=llm)
            char_descs.append(desc)

    # 获取场景描述
    scene_id = shot.get("scene", "")
    scene = sm.get_scene(scene_id)
    scene_desc = translate_to_english(scene.get("description", ""), llm=llm) if scene else ""

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
        wb = WorkflowBuilder(cfg.data, models, cfg.project_dir, comfyui=container.get("image"))
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
            wb = WorkflowBuilder(cfg.data, models, cfg.project_dir, comfyui=container.get("image"))
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

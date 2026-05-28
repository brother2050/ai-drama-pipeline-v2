"""快速预览管线 — draft/standard/high 三档

复用 pipeline.tasks 核心逻辑（tts_core / first_frame_core / video_core / lipsync_core），
不走 Celery 任务和数据库防重复，适合本地快速预览。
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infra.config import Config

logger = logging.getLogger(__name__)


def run_preview(config_path: str, episode: int, level: str = "draft", force: bool = False):
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

    # 逐镜头处理
    for shot in shots:
        sid = shot.get("shot_id", "001")
        logger.info(f"  镜头 {sid}: {shot.get('action', '')[:30]}...")

        shot_out = out_dir / f"s{sid}"
        shot_out.mkdir(parents=True, exist_ok=True)

        try:
            _process_shot(shot, cont, cfg, shot_out, preset, force=force)
        except Exception as e:
            logger.error(f"  ❌ 镜头 {sid} 失败: {e}")
            continue

    logger.info("预览完成")


def _process_shot(shot: dict, container, cfg, shot_out: Path, preset: dict, *, force: bool = False):
    """处理单个镜头（复用 pipeline.tasks 核心逻辑）"""
    from pipeline.tasks import tts_core, first_frame_core, video_core, lipsync_core

    shot_id = shot.get("shot_id", "001")

    # 应用 preset 参数：临时覆盖 generation 配置（过滤 None 值，避免覆盖已有配置）
    overrides = {k: v for k, v in {
        "image_steps": preset.get("steps"),
        "resolution": preset.get("resolution"),
        "video_frames": preset.get("video_frames"),
    }.items() if v is not None}
    orig_gen = cfg.data.get("generation", {}).copy()
    if overrides:
        cfg.data.setdefault("generation", {}).update(overrides)

    try:
        # 1) TTS 语音合成
        tts_result = tts_core(shot_id, shot, cfg, container, shot_out, force=force)
        if tts_result.get("status") == "done":
            logger.info(f"    ✅ TTS: audio.wav")
        elif tts_result.get("status") == "error":
            logger.warning(f"    ⚠ TTS 失败: {tts_result.get('reason', '')}")

        # 2) 首帧生成
        ff_result = first_frame_core(shot_id, shot, cfg, container, shot_out, force=force)
        if ff_result.get("status") == "done":
            logger.info(f"    ✅ 首帧: frame.png")
        elif ff_result.get("status") == "error":
            logger.warning(f"    ⚠ 首帧失败: {ff_result.get('reason', '')}")

        # 3) 视频生成
        vid_result = video_core(shot_id, cfg, container, shot_out, force=force)
        if vid_result.get("status") == "done":
            logger.info(f"    ✅ 视频: video.mp4")
        elif vid_result.get("status") == "error":
            logger.warning(f"    ⚠ 视频失败: {vid_result.get('reason', '')}")

        # 4) 口型同步
        ls_result = lipsync_core(shot_id, container, shot_out, force=force)
        if ls_result.get("status") == "done":
            logger.info(f"    ✅ 口型同步: synced.mp4")
        elif ls_result.get("status") == "error":
            logger.warning(f"    ⚠ 口型同步失败: {ls_result.get('reason', '')}")
    finally:
        # 恢复原始 generation 配置
        cfg.data["generation"] = orig_gen


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

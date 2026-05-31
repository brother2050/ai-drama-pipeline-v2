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
    paths = cfg.paths
    logger.info(f"预览 第{episode}集 ({level})")

    # 触发后端自注册
    from api import _ensure_registered; _ensure_registered()
    from api.registry import Container
    cont = Container(cfg.data)

    # 加载分镜
    sb_path = paths.storyboard_csv
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
    # 未配置 generation 段时，使用后端原生默认值（从模型注册表读取）
    from infra.gpu import get_generation_config
    from flow.model_registry import ModelRegistry
    gen = get_generation_config(cfg)

    # 获取当前后端的原生默认参数
    models = cfg.get("models", {})
    registry = ModelRegistry(cfg.path)
    default_img = registry.get_defaults().get("image_backend", "sd15")
    img_backend = models.get("image_backend", default_img)
    backend_defaults = registry.get_image_defaults(img_backend)
    fallback_steps = backend_defaults.get("steps", 28)
    fallback_res = [backend_defaults.get("width", 1024), backend_defaults.get("height", 576)]

    base_steps = gen.get("image_steps") or fallback_steps
    base_res = gen.get("resolution") or fallback_res
    aspect_ratio = gen.get("aspect_ratio")

    # 如果配置了 aspect_ratio 且没有精确 resolution，按比例计算
    if aspect_ratio and not gen.get("resolution"):
        from engines.workflow_builder import WorkflowBuilder
        base_res = list(WorkflowBuilder._calc_resolution(
            base_res[0], base_res[1], aspect_ratio))

    presets = {
        "draft": {"steps": max(4, base_steps // 3), "resolution": [max(256, base_res[0] // 2), max(144, base_res[1] // 2)]},
        "standard": {"steps": base_steps, "resolution": base_res},
        "high": {"steps": int(base_steps * 1.4), "resolution": [min(1920, int(base_res[0] * 1.5)), min(1080, int(base_res[1] * 1.5))]},
    }
    preset = presets.get(level, presets["draft"])

    out_dir = paths.episode_dir(episode)
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
            logger.error(f"  ❌ 镜头 {sid} 失败: {e}", exc_info=True)
            continue

    logger.info("预览完成")


def _process_shot(shot: dict, container, cfg, shot_out: Path, preset: dict, *, force: bool = False):
    """处理单个镜头（复用 pipeline.tasks 核心逻辑）"""
    from pipeline.tasks import tts_core, first_frame_core, video_core, lipsync_core

    shot_id = shot.get("shot_id", "001")

    # 应用 preset 参数：临时覆盖 generation 配置（deepcopy 避免并发修改）
    overrides = {k: v for k, v in {
        "image_steps": preset.get("steps"),
        "resolution": preset.get("resolution"),
    }.items() if v is not None}
    import copy
    orig_gen = copy.deepcopy(cfg.data.get("generation", {}))
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
        vid_result = video_core(shot_id, cfg, container, shot_out, shot=shot, force=force)
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

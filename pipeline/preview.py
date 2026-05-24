"""快速预览管线"""
from __future__ import annotations
import argparse, logging, sys, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infra.config import Config
from api.registry import container, Container

logger = logging.getLogger(__name__)

def run_preview(config_path: str, episode: int, level: str = "draft"):
    """快速预览"""
    cfg = Config(config_path)
    logger.info(f"预览 第{episode}集 ({level})")

    # 加载后端
    from api import backends  # 触发自注册
    cont = Container(cfg.data)

    # 加载分镜
    sb_path = Path(cfg.project_dir) / "storyboard" / "episodes.csv"
    if not sb_path.exists():
        logger.warning("分镜表不存在")
        return

    import csv
    shots = []
    with open(sb_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if int(row.get("episode", 0)) == episode:
                shots.append(row)

    if not shots:
        logger.warning(f"第{episode}集没有镜头")
        return

    # 预设
    presets = cfg.data.get("preview", {}).get("presets", {})
    preset = presets.get(level, presets.get("draft", {}))

    out_dir = Path(cfg.project_dir) / "output" / f"e{episode:02d}"
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"共 {len(shots)} 个镜头，预设: {level}")
    for shot in shots:
        sid = shot.get("shot_id", "001")
        logger.info(f"  镜头 {sid}: {shot.get('action', '')[:30]}...")
        # TODO: 实际生成逻辑（ComfyUI → TTS → LipSync → 后期）

    logger.info("预览完成")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", required=True)
    parser.add_argument("-e", "--episode", type=int, default=1)
    parser.add_argument("-p", "--preset", default="draft")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_preview(args.config, args.episode, args.preset)


if __name__ == "__main__":
    main()

"""后期合成"""
from __future__ import annotations
import argparse, logging, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infra.config import Config
from infra.ffmpeg import FFmpeg

logger = logging.getLogger(__name__)

def run_post(config_path: str, episode: int, vertical: bool = False):
    cfg = Config(config_path)
    logger.info(f"后期合成 第{episode}集{'（竖屏）' if vertical else ''}")

    out_dir = Path(cfg.project_dir) / "output" / f"e{episode:02d}"
    if not out_dir.exists():
        logger.warning(f"输出目录不存在: {out_dir}")
        return

    # 拼接
    videos = sorted(out_dir.glob("videos/*.mp4"))
    if not videos:
        logger.warning("没有视频文件")
        return

    concat_out = out_dir / f"episode_{episode:02d}_concat.mp4"
    FFmpeg.concat([str(v) for v in videos], str(concat_out))
    logger.info(f"拼接完成: {concat_out}")

    # 横转竖
    if vertical:
        vertical_out = out_dir / f"episode_{episode:02d}_vertical.mp4"
        FFmpeg.to_vertical(str(concat_out), str(vertical_out))
        logger.info(f"横转竖完成: {vertical_out}")

    logger.info("后期合成完成")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", required=True)
    parser.add_argument("-e", "--episode", type=int, required=True)
    parser.add_argument("--vertical", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_post(args.config, args.episode, args.vertical)

if __name__ == "__main__":
    main()

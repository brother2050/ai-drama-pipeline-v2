"""完整生产管线"""
from __future__ import annotations
import argparse, logging, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infra.config import Config

logger = logging.getLogger(__name__)

def run_produce(config_path: str, episode: int):
    cfg = Config(config_path)
    logger.info(f"完整生产 第{episode}集")
    # TODO: 实际生产逻辑
    logger.info("生产完成")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", required=True)
    parser.add_argument("-e", "--episode", type=int, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_produce(args.config, args.episode)

if __name__ == "__main__":
    main()

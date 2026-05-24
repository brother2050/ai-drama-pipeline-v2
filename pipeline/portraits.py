"""定妆照生成"""
from __future__ import annotations
import argparse, logging, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infra.config import Config

logger = logging.getLogger(__name__)

def run_portraits(config_path: str):
    cfg = Config(config_path)
    logger.info("生成定妆照")
    chars_dir = Path(cfg.project_dir) / "config" / "characters"
    if not chars_dir.exists():
        logger.warning("角色配置目录不存在")
        return
    for f in chars_dir.glob("*.yaml"):
        if f.suffix == ".yaml" and not f.stem.endswith(".example"):
            logger.info(f"  角色: {f.stem}")
            # TODO: 调用 ComfyUI 生成定妆照
    logger.info("定妆照生成完成")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_portraits(args.config)

if __name__ == "__main__":
    main()

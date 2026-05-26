"""定妆照生成 — 为所有角色生成参考图"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infra.config import Config

logger = logging.getLogger(__name__)


def run_portraits(config_path: str):
    """生成定妆照"""
    cfg = Config(config_path)
    logger.info("生成定妆照")

    # 触发后端自注册
    from api import _ensure_registered; _ensure_registered()
    from api.registry import Container

    chars_dir = Path(cfg.project_dir) / "config" / "characters"
    if not chars_dir.exists():
        logger.warning("角色配置目录不存在")
        return

    # 尝试创建容器（需要 ComfyUI）
    try:
        cont = Container(cfg.data)
    except Exception as e:
        logger.warning(f"无法创建容器: {e}")
        cont = None

    import yaml

    generated = 0
    for f in chars_dir.glob("*.yaml"):
        if f.suffix != ".yaml" or f.stem.endswith(".example"):
            continue

        with open(f) as fh:
            data = yaml.safe_load(fh) or {}
        char = data.get("character", {})
        char_id = char.get("id", f.stem)
        char_name = char.get("name", char_id)

        logger.info(f"  角色: {char_name} ({char_id})")

        portrait_dir = Path(cfg.project_dir) / "assets" / "characters" / char_id
        portrait_dir.mkdir(parents=True, exist_ok=True)

        # 检查是否已有定妆照
        existing = list(portrait_dir.glob("*.png")) + list(portrait_dir.glob("*.jpg"))
        if existing:
            logger.info(f"    已有 {len(existing)} 张定妆照，跳过")
            continue

        # 构建 prompt
        appearance = char.get("appearance", "")
        if cont:
            try:
                comfyui = cont.get("image")
                # 使用 WorkflowBuilder 构建正确的定妆照工作流
                from engines.workflow_builder import WorkflowBuilder
                models = cfg.get("models", {})
                wb = WorkflowBuilder(cfg.data, models, cfg.project_dir, comfyui=comfyui)
                wb.load_workflows()
                fake_shot = {"characters": char_id, "emotion": "neutral",
                             "shot_type": "特写", "camera": "固定"}
                _, wf = wb.build_first_frame(fake_shot, character_desc=appearance)
                if wf:
                    files = comfyui.generate(wf, str(portrait_dir))
                    if files:
                        logger.info(f"    ✅ 生成 {len(files)} 张")
                        generated += 1
                    else:
                        logger.warning(f"    ⚠ 未生成任何图片")
                else:
                    logger.warning(f"    ⚠ 工作流为空（缺少模板）")
            except Exception as e:
                logger.error(f"    ❌ 失败: {e}")
        else:
            logger.warning(f"    ⚠ 无 ComfyUI 连接，跳过")

    logger.info(f"定妆照生成完成 ({generated} 个角色)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_portraits(args.config)


if __name__ == "__main__":
    main()

"""定妆照生成 — 为所有角色生成参考图（含各服装）"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infra.config import Config

logger = logging.getLogger(__name__)


def _generate_portrait(char_id: str, appearance: str, portrait_dir: Path,
                       comfyui, wb) -> list[str]:
    """生成单张定妆照，返回生成的文件路径列表"""
    portrait_dir.mkdir(parents=True, exist_ok=True)
    fake_shot = {"characters": char_id, "emotion": "neutral",
                 "shot_type": "特写", "camera": "固定"}
    _, wf = wb.build_first_frame(fake_shot, character_desc=appearance)
    if not wf:
        logger.warning(f"    ⚠ 工作流为空（缺少模板）")
        return []
    files = comfyui.generate(wf, str(portrait_dir))
    return files or []


def _generate_outfit(char_id: str, appearance: str, outfit_key: str,
                     outfit_desc: str, base_dir: Path, comfyui, wb, llm) -> list[str]:
    """为指定服装生成参考图，返回生成的文件路径列表"""
    from engines.prompt import translate_to_english

    outfit_dir = base_dir / outfit_key
    outfit_dir.mkdir(parents=True, exist_ok=True)

    full_desc = f"{appearance}, wearing {outfit_desc}"
    if any(ord(c) > 127 for c in full_desc):
        full_desc = translate_to_english(full_desc, llm=llm)

    fake_shot = {"characters": char_id, "emotion": "neutral",
                 "shot_type": "全身", "camera": "固定"}
    _, wf = wb.build_first_frame(fake_shot, character_desc=full_desc)
    if not wf:
        logger.warning(f"      ⚠ 服装 {outfit_key} 工作流为空")
        return []
    files = comfyui.generate(wf, str(outfit_dir))
    return files or []


def run_portraits(config_path: str, force: bool = False):
    """生成定妆照（含各服装参考图）"""
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

    # 获取 LLM 实例（用于中文→英文翻译）
    llm = None
    if cont:
        try:
            llm = cont.get("llm")
            logger.info(f"LLM 后端: {type(llm).__name__}")
        except Exception as e:
            logger.warning(f"无 LLM 可用，中文角色描述将无法翻译: {e}")

    import yaml

    generated = 0
    for f in chars_dir.glob("*.yaml"):
        if f.suffix != ".yaml" or f.stem.endswith(".example"):
            continue

        try:
            with open(f) as fh:
                data = yaml.safe_load(fh) or {}
        except yaml.YAMLError as e:
            logger.warning(f"角色 YAML 格式错误 {f}: {e}")
            continue
        char = data.get("character", {})
        char_id = char.get("id", f.stem)
        char_name = char.get("name", char_id)

        logger.info(f"  角色: {char_name} ({char_id})")

        portrait_dir = Path(cfg.project_dir) / "assets" / "characters" / char_id
        portrait_dir.mkdir(parents=True, exist_ok=True)

        # 检查是否已有定妆照
        existing = list(portrait_dir.glob("*.png")) + list(portrait_dir.glob("*.jpg"))
        # 排除子目录（outfit 目录）里的图片
        existing = [img for img in existing if img.parent == portrait_dir]
        if existing:
            if force:
                for img in existing:
                    img.unlink()
                logger.info(f"    已有 {len(existing)} 张定妆照，已删除（强制模式）")
            else:
                logger.info(f"    已有 {len(existing)} 张定妆照，跳过主图")
                existing = []  # 跳过主图，但仍然检查 outfits

        appearance = char.get("appearance", "")
        if not cont:
            logger.warning(f"    ⚠ 无 ComfyUI 连接，跳过")
            continue

        try:
            comfyui = cont.get("image")
            from engines.workflow_builder import WorkflowBuilder
            models = cfg.get("models", {})
            wb = WorkflowBuilder(cfg.data, models, cfg.project_dir, comfyui=comfyui, llm=llm)
            wb.load_workflows()

            # ── 1. 生成主定妆照 ──
            if existing:
                # 已有主图，用已有的
                img_url = f"/api/assets/characters/{char_id}/{existing[0].name}"
                logger.info(f"    ⏭ 主图已存在: {existing[0].name}")
            else:
                files = _generate_portrait(char_id, appearance, portrait_dir, comfyui, wb)
                if files:
                    img_url = f"/api/assets/characters/{char_id}/{Path(files[0]).name}"
                    logger.info(f"    ✅ 主图生成完成")
                    generated += 1
                else:
                    logger.warning(f"    ⚠ 主图未生成")
                    img_url = ""

            # 回写主图 reference_images
            if img_url:
                char.setdefault("reference_images", [])
                prefix = f"/api/assets/characters/{char_id}/cover"
                char["reference_images"] = [u for u in char["reference_images"] if not u.startswith(prefix)]
                char["reference_images"].append(img_url)

            # ── 2. 遍历服装，生成各 outfit 参考图 ──
            outfits = char.get("outfits", {})
            if isinstance(outfits, dict) and outfits:
                logger.info(f"    👗 服装: {', '.join(outfits.keys())}")
                for outfit_key, outfit_val in outfits.items():
                    if not isinstance(outfit_val, dict):
                        continue
                    outfit_desc = outfit_val.get("description", "")
                    if not outfit_desc:
                        logger.debug(f"      ⏭ {outfit_key}: 无描述，跳过")
                        continue

                    outfit_dir = portrait_dir / outfit_key
                    outfit_existing = list(outfit_dir.glob("*.png")) + list(outfit_dir.glob("*.jpg"))
                    if outfit_existing and not force:
                        logger.info(f"      ⏭ {outfit_key}: 已有图，跳过")
                        continue

                    if force:
                        for img in outfit_existing:
                            img.unlink()

                    logger.info(f"      🎨 生成 {outfit_key}...")
                    try:
                        files = _generate_outfit(
                            char_id, appearance, outfit_key, outfit_desc,
                            portrait_dir, comfyui, wb, llm)
                        if files:
                            outfit_url = f"/api/assets/characters/{char_id}/{outfit_key}/{Path(files[0]).name}"
                            outfit_val.setdefault("reference_images", [])
                            prefix = f"/api/assets/characters/{char_id}/{outfit_key}/cover"
                            outfit_val["reference_images"] = [u for u in outfit_val["reference_images"] if not u.startswith(prefix)]
                            outfit_val["reference_images"].append(outfit_url)
                            logger.info(f"      ✅ {outfit_key} 生成完成")
                        else:
                            logger.warning(f"      ⚠ {outfit_key} 未生成")
                    except Exception as e:
                        logger.error(f"      ❌ {outfit_key} 失败: {e}")

            # ── 3. 写回 YAML ──
            data["character"] = char
            with open(f, "w", encoding="utf-8") as fh:
                yaml.dump(data, fh, allow_unicode=True, default_flow_style=False)
            logger.info(f"    📝 已更新 YAML")

        except Exception as e:
            logger.error(f"    ❌ 失败: {e}")

    logger.info(f"定妆照生成完成 ({generated} 个角色)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_portraits(args.config)


if __name__ == "__main__":
    main()

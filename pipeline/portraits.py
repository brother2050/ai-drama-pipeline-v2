"""定妆照生成 — 为角色生成三视图 + 各服装参考图

被以下入口调用：
- portraits_task / drama portraits CLI（批量，Celery）
- portrait_single_task（单角色，Celery）
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infra.config import Config

logger = logging.getLogger(__name__)

# 三视图配置
_THREE_VIEWS = [
    ("cover.png", "特写", "正面"),
    ("side.png",  "侧面特写", "侧面"),
    ("back.png",  "背面特写", "背面"),
]


def _char_seed(char_id: str) -> int:
    """为角色生成确定性 seed"""
    import hashlib
    h = hashlib.md5(char_id.encode("utf-8")).hexdigest()
    return int(h[:16], 16)


def _generate_view(char_id: str, appearance: str, portrait_dir: Path,
                   comfyui, wb, filename: str, shot_type: str,
                   seed: int | None = None,
                   ref_image: str | None = None) -> bool:
    """生成单张视图，成功返回 True

    Args:
        seed: 指定 seed 保持一致性
        ref_image: IP-Adapter 参考图路径（side/back 用 cover 做参考）
    """
    fake_shot = {"characters": char_id, "emotion": "neutral",
                 "shot_type": shot_type, "camera": "固定"}
    _, wf = wb.build_first_frame(fake_shot, character_desc=appearance, seed=seed)
    if not wf:
        return False

    # 注入参考图到 IP-Adapter
    if ref_image and os.path.exists(ref_image):
        from engines.workflow import find_character_load_image_nodes
        char_nodes = find_character_load_image_nodes(wf)
        if char_nodes:
            wf[char_nodes[0]]["inputs"]["image"] = os.path.basename(ref_image)
            try:
                comfyui.upload_image(ref_image)
            except Exception as e:
                logger.warning(f"参考图上传失败: {e}")

    files = comfyui.generate(wf, str(portrait_dir))
    if not files:
        return False
    target = portrait_dir / filename
    os.replace(files[0], str(target))
    return True


def _generate_outfit(char_id: str, appearance: str, outfit_key: str,
                     outfit_desc: str, base_dir: Path, comfyui, wb, llm,
                     seed: int | None = None,
                     ref_image: str | None = None) -> bool:
    """为指定服装生成参考图，成功返回 True

    Args:
        seed: 指定 seed 保持一致性
        ref_image: IP-Adapter 参考图路径（用 cover 保持面部一致）
    """
    from engines.prompt import translate_to_english

    outfit_dir = base_dir / outfit_key
    outfit_dir.mkdir(parents=True, exist_ok=True)

    full_desc = f"{appearance}, wearing {outfit_desc}"
    if any(ord(c) > 127 for c in full_desc):
        full_desc = translate_to_english(full_desc, llm=llm)

    fake_shot = {"characters": char_id, "emotion": "neutral",
                 "shot_type": "全身", "camera": "固定"}
    _, wf = wb.build_first_frame(fake_shot, character_desc=full_desc, seed=seed)
    if not wf:
        return False

    # 注入 cover 参考图
    if ref_image and os.path.exists(ref_image):
        from engines.workflow import find_character_load_image_nodes
        char_nodes = find_character_load_image_nodes(wf)
        if char_nodes:
            wf[char_nodes[0]]["inputs"]["image"] = os.path.basename(ref_image)
            try:
                comfyui.upload_image(ref_image)
            except Exception as e:
                logger.warning(f"参考图上传失败: {e}")

    files = comfyui.generate(wf, str(outfit_dir))
    if not files:
        return False
    # 重命名为 cover.png
    cover_path = outfit_dir / "cover.png"
    os.replace(files[0], str(cover_path))
    return True


def run_portraits(
    config_path: str,
    *,
    force: bool = False,
    char_ids: list[str] | None = None,
    write_db: bool = False,
):
    """生成定妆照（三视图 + 各服装参考图）

    Args:
        config_path: 项目配置文件路径
        force: True 时删除已有图片重新生成
        char_ids: None=全部角色, list=只处理指定角色
        write_db: True 时同步写入数据库
    """
    cfg = Config(config_path)
    logger.info("生成定妆照（三视图）")

    from api import _ensure_registered; _ensure_registered()
    from api.registry import Container

    chars_dir = Path(cfg.project_dir) / "config" / "characters"
    if not chars_dir.exists():
        logger.warning("角色配置目录不存在")
        return

    try:
        cont = Container(cfg.data)
    except Exception as e:
        logger.warning(f"无法创建容器: {e}")
        cont = None

    llm = None
    if cont:
        try:
            llm = cont.get("llm")
            logger.info(f"LLM 后端: {type(llm).__name__}")
        except Exception as e:
            logger.warning(f"无 LLM 可用: {e}")

    if char_ids is not None:
        char_files = []
        for cid in char_ids:
            p = chars_dir / f"{cid}.yaml"
            if p.exists():
                char_files.append(p)
    else:
        char_files = [f for f in chars_dir.glob("*.yaml")
                      if f.suffix == ".yaml" and not f.stem.endswith(".example")]

    generated = 0
    for f in char_files:
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

        if not cont:
            logger.warning(f"    ⚠ 无 ComfyUI 连接，跳过")
            continue

        appearance = char.get("appearance", "")

        try:
            comfyui = cont.get("image")
            from engines.workflow_builder import WorkflowBuilder
            models = cfg.get("models", {})
            wb = WorkflowBuilder(cfg.data, models, cfg.project_dir, comfyui=comfyui, llm=llm)
            wb.load_workflows()

            # ── 1. 生成三视图 ──
            base_seed = _char_seed(char_id)
            cover_path = portrait_dir / "cover.png"
            char_generated = 0
            for i, (filename, shot_type, label) in enumerate(_THREE_VIEWS):
                view_path = portrait_dir / filename
                if view_path.exists() and not force:
                    logger.info(f"    ⏭ {label}视图已存在: {filename}")
                    continue

                old_file = view_path if view_path.exists() else None
                logger.info(f"    🎨 生成{label}视图 ({filename})...")

                # cover 用基础 seed，side/back 用 seed+偏移
                view_seed = base_seed + i
                # side/back 用 cover 做 IP-Adapter 参考
                ref = str(cover_path) if i > 0 and cover_path.exists() else None

                try:
                    ok = _generate_view(char_id, appearance, portrait_dir, comfyui, wb,
                                        filename, shot_type, seed=view_seed, ref_image=ref)
                    if ok:
                        if old_file and force:
                            pass  # os.replace 已覆盖
                        logger.info(f"    ✅ {label}视图完成 (seed={view_seed})")
                        char_generated += 1
                    else:
                        logger.warning(f"    ⚠ {label}视图未生成")
                except Exception as e:
                    logger.error(f"    ❌ {label}视图失败: {e}")

            if char_generated > 0:
                generated += 1

            # ── 2. 回写三视图 reference_images ──
            view_urls = []
            for filename, _, _ in _THREE_VIEWS:
                if (portrait_dir / filename).exists():
                    view_urls.append(f"/api/assets/characters/{char_id}/{filename}")

            if view_urls:
                char.setdefault("reference_images", [])
                prefix = f"/api/assets/characters/{char_id}/"
                # 保留非本角色的引用 + 本角色的三视图引用
                char["reference_images"] = [
                    u for u in char["reference_images"]
                    if not u.startswith(prefix) or any(u.endswith(f"/{fn}") for fn, _, _ in _THREE_VIEWS)
                ]
                existing_set = set(char["reference_images"])
                for url in view_urls:
                    if url not in existing_set:
                        char["reference_images"].append(url)

            # ── 3. 遍历服装 ──
            outfits = char.get("outfits", {})
            if isinstance(outfits, dict) and outfits:
                logger.info(f"    👗 服装: {', '.join(outfits.keys())}")
                for outfit_idx, (outfit_key, outfit_val) in enumerate(outfits.items()):
                    if not isinstance(outfit_val, dict):
                        continue
                    outfit_desc = outfit_val.get("description", "")
                    if not outfit_desc:
                        continue

                    outfit_dir = portrait_dir / outfit_key
                    outfit_existing = list(outfit_dir.glob("*.png")) + list(outfit_dir.glob("*.jpg"))
                    if outfit_existing and not force:
                        logger.info(f"      ⏭ {outfit_key}: 已有图，跳过")
                        continue

                    # 服装 seed = base_seed + 100 + index（与三视图错开）
                    outfit_seed = base_seed + 100 + outfit_idx
                    # 用 cover 做参考保持面部一致
                    ref = str(cover_path) if cover_path.exists() else None

                    logger.info(f"      🎨 生成 {outfit_key}...")
                    try:
                        ok = _generate_outfit(
                            char_id, appearance, outfit_key, outfit_desc,
                            portrait_dir, comfyui, wb, llm,
                            seed=outfit_seed, ref_image=ref)
                        if ok:
                            outfit_url = f"/api/assets/characters/{char_id}/{outfit_key}/cover.png"
                            outfit_val.setdefault("reference_images", [])
                            prefix = f"/api/assets/characters/{char_id}/{outfit_key}/cover"
                            outfit_val["reference_images"] = [u for u in outfit_val["reference_images"] if not u.startswith(prefix)]
                            outfit_val["reference_images"].append(outfit_url)
                            logger.info(f"      ✅ {outfit_key} 完成 (seed={outfit_seed})")
                        else:
                            logger.warning(f"      ⚠ {outfit_key} 未生成")
                    except Exception as e:
                        logger.error(f"      ❌ {outfit_key} 失败: {e}")

            # ── 4. 写回 YAML ──
            data["character"] = char
            from infra.config import save_yaml
            save_yaml(f, data)
            logger.info(f"    📝 已更新 YAML")

            # ── 5. 同步数据库 ──
            if write_db:
                try:
                    from infra.database.characters import upsert as db_up
                    from infra.database.pool import get_pool
                    db_up(get_pool(), char_id, char)
                except Exception as e:
                    logger.debug(f"DB 写入跳过: {e}")

        except Exception as e:
            logger.error(f"    ❌ 失败: {e}")

    logger.info(f"定妆照生成完成 ({generated} 个角色)")
    return {"status": "done", "generated": generated, "total": len(char_files)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_portraits(args.config)


if __name__ == "__main__":
    main()

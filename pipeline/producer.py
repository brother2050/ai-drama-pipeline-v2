"""完整生产管线 — 全流程：首帧→视频→音频→口型同步→后期"""
from __future__ import annotations

import argparse
import csv
import hashlib
import logging
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infra.config import Config

logger = logging.getLogger(__name__)


def run_produce(config_path: str, episode: int, force: bool = False):
    """完整生产"""
    cfg = Config(config_path)
    logger.info(f"完整生产 第{episode}集")

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

    out_dir = Path(cfg.project_dir) / "output" / f"e{episode:02d}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 加载角色和场景配置
    from engines.shot_manager import ShotManager
    config_dir = Path(cfg.project_dir) / "config"
    sm = ShotManager(str(sb_path), str(config_dir), cfg.data)

    logger.info(f"共 {len(shots)} 个镜头")

    # 生成字幕
    from post.subtitle import generate_srt
    srt_path = out_dir / f"episode_{episode:02d}.srt"
    generate_srt(shots, str(srt_path))

    # 逐镜头处理
    for i, shot in enumerate(shots, 1):
        sid = shot.get("shot_id", "001")
        logger.info(f"[{i}/{len(shots)}] 镜头 {sid}: {shot.get('action', '')[:40]}")

        shot_out = out_dir / f"s{sid}"
        shot_out.mkdir(parents=True, exist_ok=True)

        try:
            _produce_shot(shot, sm, cont, cfg, shot_out, force=force)
        except Exception as e:
            logger.error(f"  ❌ 镜头 {sid} 失败: {e}")
            import traceback
            traceback.print_exc()
            continue

    # 后期合成
    logger.info("━━━ 后期合成 ━━━")
    try:
        from post.production import run_post
        run_post(config_path, episode)
    except Exception as e:
        logger.error(f"后期合成失败: {e}")

    logger.info("生产完成")


def _produce_shot(shot: dict, sm, container, cfg, shot_out: Path, *, force: bool = False):
    """生产单个镜头"""
    from engines.prompt import translate_to_english

    char_ids = [c.strip() for c in shot.get("characters", "").split("+") if c.strip()]

    # ── 1. TTS 语音合成 ──
    dialogue = shot.get("dialogue", "").strip()
    audio_path = shot_out / "audio.wav"
    if dialogue and dialogue != "......":
        if not force and audio_path.exists():
            logger.info(f"  ⏭ TTS 跳过（音频已存在）")
        else:
            try:
                tts = container.get("tts")
                char = sm.get_character(char_ids[0]) if char_ids else {}
                voice_config = char.get("voice", {})
                emotion = shot.get("emotion", "neutral")
                language = shot.get("language", "zh")
                tts.synthesize(dialogue, str(audio_path), voice_config=voice_config,
                               emotion=emotion, language=language)
                logger.info(f"  ✅ TTS 完成")
            except Exception as e:
                logger.warning(f"  ⚠ TTS 失败: {e}")

    # ── 2. 首帧生成（使用 WorkflowBuilder 含 IP-Adapter）──
    frame_path = shot_out / "frame.png"
    if not force and frame_path.exists():
        logger.info(f"  ⏭ 首帧跳过（frame.png 已存在）")
    else:
        try:
            from engines.workflow_builder import WorkflowBuilder
            from engines.multi_char import MultiCharacterHandler

            # LLM 仅在预翻译字段缺失时使用
            llm = None
            try:
                if cfg.get("llm", {}).get("enabled"):
                    llm = container.get("llm")
            except Exception:
                pass

            # 优先读预翻译的 appearance_en
            char_descs = []
            for cid in char_ids:
                char = sm.get_character(cid)
                if char:
                    desc_en = char.get("appearance_en", "")
                    if desc_en:
                        char_descs.append(desc_en)
                    else:
                        char_descs.append(translate_to_english(char.get("appearance", ""), llm=llm))

            # 优先读预翻译的 description_en
            scene_id = shot.get("scene", "")
            scene = sm.get_scene(scene_id)
            if scene:
                scene_desc = scene.get("description_en", "") or translate_to_english(scene.get("description", ""), llm=llm)
            else:
                scene_desc = ""

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

                from engines.workflow import find_lora_nodes
                from infra.asset_tracker import AssetTracker
                from urllib.parse import urlparse

                tracker = AssetTracker(cfg.project_dir)
                image_server_url = comfyui.url
                lora_nodes = find_lora_nodes(wf)
                for node_id, lora_name in lora_nodes:
                    if tracker.is_lora_tracked(image_server_url, lora_name):
                        continue
                    parsed = urlparse(image_server_url)
                    is_local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
                    found = False
                    if is_local:
                        for d in [Path.home() / "ComfyUI" / "models" / "loras",
                                  Path("/opt/ComfyUI/models/loras")]:
                            if (d / lora_name).exists():
                                tracker.mark_lora_tracked(image_server_url, lora_name)
                                found = True
                                break
                    if not found:
                        logger.warning(
                            f"  ⚠ LoRA '{lora_name}' 未确认存在于服务器 {image_server_url}")

                for node_id, file_path in wb.build_upload_map(shot, wf).items():
                    if Path(file_path).exists():
                        try:
                            comfyui.upload_image(file_path)
                            if node_id in wf and wf[node_id].get("class_type") in ("LoadImage", "LoadImageFromPath", "ImageLoad"):
                                wf[node_id]["inputs"]["image"] = Path(file_path).name
                        except Exception as e:
                            logger.warning(f"  ⚠ 参考图上传失败 [{node_id}]: {e}")
                files = comfyui.generate(wf, str(shot_out))
                if files:
                    os.replace(files[0], frame_path)
                    logger.info(f"  ✅ 首帧完成")
        except Exception as e:
            logger.warning(f"  ⚠ 首帧失败: {e}")

    # ── 3. 视频生成 ──
    video_path = shot_out / "video.mp4"
    if not force and video_path.exists():
        logger.info(f"  ⏭ 视频跳过（video.mp4 已存在）")
    elif frame_path.exists():
        try:
            from engines.workflow_builder import WorkflowBuilder
            from engines.workflow import find_load_image_nodes
            models = cfg.get("models", {})
            wb = WorkflowBuilder(cfg.data, models, cfg.project_dir, comfyui=container.get("image"))
            wb.load_workflows()
            video_wf = wb.build_video(str(frame_path), shot=shot)

            if video_wf:
                video_backend = container.get("video")

                # 智能判断是否需要上传首帧图（全局唯一文件名避免跨项目/跨集覆盖）
                load_nodes = find_load_image_nodes(video_wf)
                if load_nodes:
                    video_comfyui = video_backend._get_comfyui() if hasattr(video_backend, "_get_comfyui") else video_backend
                    shot_id = shot.get("shot_id", "000")
                    project_name = os.path.basename(cfg.project_dir) or "project"
                    # ComfyUI LoadImage 节点不接受非 ASCII 文件名
                    if re.search(r'[^\x00-\x7f]', project_name):
                        ascii_name = "proj_" + hashlib.md5(project_name.encode("utf-8")).hexdigest()[:8]
                    else:
                        ascii_name = project_name
                    # 从路径提取集号: .../output/ep01/001/ → ep01
                    ep_tag = ""
                    parent = shot_out.parent.name
                    if parent.startswith("ep") and parent[2:].isdigit():
                        ep_tag = f"_{parent}"
                    server_filename = f"{ascii_name}{ep_tag}_{shot_id}_frame.png"

                    # 判断是否需要上传：tracker 记录 + 服务端存在 → 跳过
                    # 避免"删除项目→重建同名"时旧图残留
                    from infra.asset_tracker import AssetTracker
                    tracker = AssetTracker(cfg.project_dir)
                    video_server_url = getattr(video_comfyui, "url", "").rstrip("/")
                    already_tracked = tracker.is_image_tracked(video_server_url, server_filename)

                    need_upload = True
                    if already_tracked:
                        try:
                            if video_comfyui.check_image_exists(server_filename, asset_type="input"):
                                need_upload = False
                            else:
                                tracker.untrack_image(video_server_url, server_filename)
                        except Exception:
                            pass
                    if need_upload:
                        try:
                            video_comfyui.upload_image(str(frame_path), filename=server_filename)
                            tracker.mark_image_tracked(video_server_url, server_filename)
                        except Exception as e:
                            logger.warning(f"  ⚠ 首帧上传失败: {e}")
                    # 始终更新工作流节点引用
                    if load_nodes[0] in video_wf:
                        video_wf[load_nodes[0]]["inputs"]["image"] = server_filename

                files = video_backend.generate(video_wf, str(shot_out))
                if files:
                    os.replace(files[0], video_path)
                    logger.info(f"  ✅ 视频完成")
        except Exception as e:
            logger.warning(f"  ⚠ 视频失败: {e}")

    # ── 4. 口型同步 ──
    synced_path = shot_out / "synced.mp4"
    if not force and synced_path.exists():
        logger.info(f"  ⏭ 口型同步跳过（synced.mp4 已存在）")
    elif video_path.exists() and audio_path.exists():
        try:
            lipsync = container.get("lipsync")
            lipsync.sync(str(video_path), str(audio_path), str(synced_path))
            logger.info(f"  ✅ 口型同步完成")
        except Exception as e:
            logger.warning(f"  ⚠ 口型同步失败: {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", required=True)
    parser.add_argument("-e", "--episode", type=int, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_produce(args.config, args.episode)


if __name__ == "__main__":
    main()

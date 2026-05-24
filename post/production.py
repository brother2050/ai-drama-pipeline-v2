"""后期合成 — 拼接、转场、字幕、配乐、横转竖"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infra.config import Config
from infra.ffmpeg import FFmpeg

logger = logging.getLogger(__name__)


def run_post(config_path: str, episode: int, vertical: bool = False):
    """后期合成：拼接所有镜头视频 → 添加字幕/配乐 → 可选横转竖"""
    cfg = Config(config_path)
    logger.info(f"后期合成 第{episode}集{'（竖屏）' if vertical else ''}")

    out_dir = Path(cfg.project_dir) / "output" / f"e{episode:02d}"
    if not out_dir.exists():
        logger.warning(f"输出目录不存在: {out_dir}")
        return

    # 收集所有镜头视频（按 shot_id 排序）
    videos = []
    for shot_dir in sorted(out_dir.glob("s*")):
        # 优先用 synced.mp4（口型同步后的），其次 video.mp4
        synced = shot_dir / "synced.mp4"
        video = shot_dir / "video.mp4"
        if synced.exists():
            videos.append(synced)
        elif video.exists():
            videos.append(video)

    if not videos:
        logger.warning("没有视频文件")
        return

    # 拼接
    transition = cfg.get("post_production.transition", "crossfade")
    transition_duration = cfg.get("post_production.transition_duration", 0.5)
    concat_out = out_dir / f"episode_{episode:02d}_concat.mp4"

    try:
        FFmpeg.concat([str(v) for v in videos], str(concat_out),
                      transition=transition, duration=transition_duration)
        logger.info(f"拼接完成: {concat_out}")
    except Exception as e:
        logger.error(f"拼接失败: {e}")
        # 回退：简单拼接（无转场）
        FFmpeg.concat([str(v) for v in videos], str(concat_out), transition="none")
        logger.info(f"简单拼接完成: {concat_out}")

    # 添加字幕（如果有 SRT）
    srt_path = out_dir / f"episode_{episode:02d}.srt"
    if srt_path.exists():
        subtitled_out = out_dir / f"episode_{episode:02d}_subtitled.mp4"
        try:
            FFmpeg.add_subtitle(str(concat_out), str(srt_path), str(subtitled_out))
            logger.info(f"字幕添加完成: {subtitled_out}")
            concat_out = subtitled_out
        except Exception as e:
            logger.warning(f"字幕添加失败（跳过）: {e}")

    # 混合配乐（如果有 BGM）
    bgm_path = out_dir / "bgm.wav"
    if bgm_path.exists():
        bgm_out = out_dir / f"episode_{episode:02d}_with_bgm.mp4"
        bgm_volume = cfg.get("post_production.bgm_volume", 0.15)
        try:
            FFmpeg.mix_audio(str(concat_out), str(bgm_path), str(bgm_out),
                             video_vol=1.0, audio_vol=bgm_volume)
            logger.info(f"配乐混合完成: {bgm_out}")
            concat_out = bgm_out
        except Exception as e:
            logger.warning(f"配乐混合失败（跳过）: {e}")

    # 横转竖
    if vertical:
        from post.vertical import to_vertical
        vertical_out = out_dir / f"episode_{episode:02d}_vertical.mp4"
        try:
            to_vertical(str(concat_out), str(vertical_out), mode="face_track")
            logger.info(f"横转竖完成: {vertical_out}")
            concat_out = vertical_out
        except Exception as e:
            logger.error(f"横转竖失败: {e}")

    # 最终输出重命名为 final.mp4（统一命名，flow/episode.py 依赖此文件名）
    final_out = out_dir / f"episode_{episode:02d}_final.mp4"
    try:
        import shutil
        shutil.copy2(str(concat_out), str(final_out))
        logger.info(f"最终输出: {final_out}")
    except Exception as e:
        logger.warning(f"复制到 final 失败: {e}")

    # 清理中间文件（保留 final 和原始镜头视频）
    # 注意: concat_out 可能是 _concat/_subtitled/_with_bgm/_vertical 中的一个
    # 只删除不同于 concat_out 和 final_out 的中间文件
    for intermediate in [out_dir / f"episode_{episode:02d}_concat.mp4",
                         out_dir / f"episode_{episode:02d}_subtitled.mp4",
                         out_dir / f"episode_{episode:02d}_with_bgm.mp4",
                         out_dir / f"episode_{episode:02d}_vertical.mp4"]:
        if intermediate.exists() and intermediate != final_out and intermediate != concat_out:
            try:
                intermediate.unlink()
            except OSError:
                pass

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

"""管线编排器 — 单镜头全流程"""
from __future__ import annotations
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 阶段定义
STAGES = ["first_frame", "video", "audio", "lip_sync", "post"]


class ShotOrchestrator:
    """单镜头编排器 — 按阶段顺序执行"""

    def __init__(self, config: dict, container=None):
        self._config = config
        self._container = container
        self._project_dir = config.get("_project_dir", os.getcwd())

    def run_shot(self, shot: dict, episode: int, *,
                 stages: list[str] | None = None, preset: str = "") -> dict[str, Any]:
        """执行单镜头全流程"""
        shot_id = shot.get("shot_id", "001")
        stages = stages or STAGES
        results = {"shot_id": shot_id, "episode": episode, "stages": {}}

        out_dir = Path(self._project_dir) / "output" / f"e{episode:02d}" / f"s{shot_id}"
        out_dir.mkdir(parents=True, exist_ok=True)

        for stage in stages:
            try:
                logger.info(f"[{shot_id}] 阶段: {stage}")
                result = self._run_stage(stage, shot, out_dir, preset)
                results["stages"][stage] = {"status": "done", **result}
            except Exception as e:
                logger.error(f"[{shot_id}] {stage} 失败: {e}")
                results["stages"][stage] = {"status": "error", "error": str(e)}
                break

        return results

    def _run_stage(self, stage: str, shot: dict, out_dir: Path, preset: str) -> dict:
        if stage == "first_frame":
            return self._stage_first_frame(shot, out_dir)
        elif stage == "video":
            return self._stage_video(shot, out_dir)
        elif stage == "audio":
            return self._stage_audio(shot, out_dir)
        elif stage == "lip_sync":
            return self._stage_lip_sync(shot, out_dir)
        elif stage == "post":
            return self._stage_post(shot, out_dir)
        return {}

    def _stage_first_frame(self, shot: dict, out_dir: Path) -> dict:
        """首帧生成"""
        from engines.prompt import build_prompt, translate_to_english
        action_en = translate_to_english(shot.get("action", ""))
        prompt = build_prompt({**shot, "action_en": action_en},
                              style=self._config.get("project", {}).get("style", "cinematic"),
                              genre=self._config.get("project", {}).get("genre", "urban"))
        output = out_dir / "frame.png"
        if self._container:
            comfyui = self._container.get("image")
            files = comfyui.generate({"prompt": {"positive": prompt}}, str(out_dir))
            if files:
                Path(files[0]).rename(output)
        return {"path": str(output), "prompt": prompt}

    def _stage_video(self, shot: dict, out_dir: Path) -> dict:
        """视频生成"""
        output = out_dir / "video.mp4"
        return {"path": str(output)}

    def _stage_audio(self, shot: dict, out_dir: Path) -> dict:
        """语音合成"""
        dialogue = shot.get("dialogue", "").strip()
        output = out_dir / "audio.wav"
        if dialogue and dialogue != "......" and self._container:
            tts = self._container.get("tts")
            tts.synthesize(dialogue, str(output))
        return {"path": str(output)}

    def _stage_lip_sync(self, shot: dict, out_dir: Path) -> dict:
        """口型同步"""
        video = out_dir / "video.mp4"
        audio = out_dir / "audio.wav"
        output = out_dir / "synced.mp4"
        if video.exists() and audio.exists() and self._container:
            lipsync = self._container.get("lipsync")
            lipsync.sync(str(video), str(audio), str(output))
        return {"path": str(output)}

    def _stage_post(self, shot: dict, out_dir: Path) -> dict:
        """后期合成"""
        output = out_dir / "final.mp4"
        return {"path": str(output)}

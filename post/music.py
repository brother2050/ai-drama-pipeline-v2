"""配乐生成 — 模板 / MusicGen / Suno"""
from __future__ import annotations
import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class MusicGenerator:
    """配乐生成器"""
    def __init__(self, backend: str = "template", config: dict | None = None, timeouts: dict | None = None):
        self._backend = backend
        self._config = config or {}
        self._timeouts = timeouts or {}

    def generate(self, duration: float, output: str, *, mood: str = "neutral") -> str:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        if self._backend == "template":
            return self._template(duration, output, mood)
        elif self._backend == "musicgen":
            return self._musicgen(duration, output, mood)
        else:
            logger.warning(f"未知配乐后端: {self._backend}，回退模板")
            return self._template(duration, output, mood)

    def _template(self, duration: float, output: str, mood: str) -> str:
        """ffmpeg 模板配乐"""
        freq = {"happy": 440, "sad": 330, "angry": 520, "romantic": 392}.get(mood, 400)
        ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
        cmd = [ffmpeg, "-y", "-f", "lavfi", "-i",
               f"sine=frequency={freq}:duration={duration}",
               "-af", "volume=0.1,tremolo=f=3:d=0.4", output]
        subprocess.run(cmd, capture_output=True, timeout=30)
        return output

    def _musicgen(self, duration: float, output: str, mood: str) -> str:
        """MusicGen API 配乐"""
        api_url = self._config.get("models", {}).get("musicgen", {}).get("api_url", "")
        if not api_url:
            return self._template(duration, output, mood)
        import httpx
        try:
            with httpx.Client(timeout=self._timeouts.get("music", 120)) as c:
                r = c.post(f"{api_url}/generate", json={
                    "prompt": f"{mood} background music", "duration": duration})
                r.raise_for_status()
                with open(output, "wb") as f: f.write(r.content)
            return output
        except Exception as e:
            logger.warning(f"MusicGen 失败: {e}，回退模板")
            return self._template(duration, output, mood)

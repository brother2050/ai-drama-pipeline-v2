"""MuseTalk 口型同步 — HTTP API"""
from __future__ import annotations
import logging, os
from pathlib import Path
import httpx
from api.registry import BackendMeta, registry

logger = logging.getLogger(__name__)

class MuseTalk:
    def __init__(self, config: dict):
        self._url = config.get("api_url", "http://127.0.0.1:8080")
        self._timeout = config.get("timeouts", {}).get("lipsync", 120)
        self._client = httpx.Client(timeout=self._timeout)
        self._fast_client = httpx.Client(timeout=3)

    @property
    def name(self): return "musetalk"

    def sync(self, video: str, audio: str, output: str) -> str:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        with open(video, "rb") as vf, open(audio, "rb") as af:
            r = self._client.post(f"{self._url}/process",
                       files={"video": (Path(video).name, vf), "audio": (Path(audio).name, af)},
                       data={"result_type": "video"})
        r.raise_for_status()
        with open(output, "wb") as f:
            f.write(r.content)
        return output

    def health_check(self):
        try:
            r = self._fast_client.get(self._url)
            return True, f"MuseTalk reachable (HTTP {r.status_code})"
        except Exception as e:
            return False, f"MuseTalk unreachable: {e}"

    def shutdown(self):
        self._client.close()
        self._fast_client.close()

def _f(config): return MuseTalk(config)
registry.register(BackendMeta(name="musetalk", service_type="lipsync", factory=_f,
    description="MuseTalk 口型同步", priority=10, tags=["api"]))


class SadTalker:
    def __init__(self, config: dict):
        self._url = config.get("api_url", "http://127.0.0.1:8082")
        self._timeout = config.get("timeouts", {}).get("lipsync", 120)
        self._client = httpx.Client(timeout=self._timeout)
        self._fast_client = httpx.Client(timeout=3)

    @property
    def name(self): return "sadtalker"

    def sync(self, video: str, audio: str, output: str) -> str:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        with open(video, "rb") as vf, open(audio, "rb") as af:
            r = self._client.post(f"{self._url}/process",
                       files={"source_video": vf, "driven_audio": af})
        r.raise_for_status()
        with open(output, "wb") as f:
            f.write(r.content)
        return output

    def health_check(self):
        try:
            r = self._fast_client.get(self._url)
            return True, f"SadTalker reachable (HTTP {r.status_code})"
        except Exception as e:
            return False, f"SadTalker unreachable: {e}"

    def shutdown(self):
        self._client.close()
        self._fast_client.close()

def _f2(config): return SadTalker(config)
registry.register(BackendMeta(name="sadtalker", service_type="lipsync", factory=_f2,
    description="SadTalker 口型同步", priority=50, tags=["api"]))

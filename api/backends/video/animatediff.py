"""AnimateDiff 视频生成 — ComfyUI API"""
from __future__ import annotations
import logging
from api.registry import BackendMeta, registry

logger = logging.getLogger(__name__)

class AnimateDiff:
    """AnimateDiff 视频后端（通过 ComfyUI API 调用）"""
    def __init__(self, config: dict):
        self._config = config
        self._comfyui_url = (config.get("comfyui_url")
                             or config.get("url")
                             or "http://127.0.0.1:8188").rstrip("/")
        self._timeout = config.get("timeouts", {}).get("comfyui", 300)
    @property
    def name(self): return "animatediff"
    def generate(self, workflow: dict, output_dir: str) -> list[str]:
        from api.backends.image.comfyui import ComfyUI
        comfyui = ComfyUI({"url": self._comfyui_url, "timeout": self._timeout})
        return comfyui.generate(workflow, output_dir)
    def health_check(self):
        import httpx
        try:
            with httpx.Client(timeout=3) as c:
                r = c.get(f"{self._comfyui_url}/system_stats")
                return True, f"AnimateDiff via ComfyUI (HTTP {r.status_code})"
        except Exception as e: return False, str(e)
    def shutdown(self): pass

def _f(config): return AnimateDiff(config)
registry.register(BackendMeta(name="animatediff", service_type="video", factory=_f,
    description="AnimateDiff 视频生成（via ComfyUI）", priority=10, tags=["api"]))


class CogVideoX:
    """CogVideoX 视频生成 — ComfyUI API"""
    def __init__(self, config: dict):
        self._config = config
        self._comfyui_url = (config.get("comfyui_url")
                             or config.get("url")
                             or "http://127.0.0.1:8188").rstrip("/")
        self._timeout = config.get("timeouts", {}).get("comfyui", 300)
    @property
    def name(self): return "cogvideox"
    def generate(self, workflow: dict, output_dir: str) -> list[str]:
        from api.backends.image.comfyui import ComfyUI
        comfyui = ComfyUI({"url": self._comfyui_url, "timeout": self._timeout})
        return comfyui.generate(workflow, output_dir)
    def health_check(self):
        import httpx
        try:
            with httpx.Client(timeout=3) as c:
                r = c.get(f"{self._comfyui_url}/system_stats")
                return True, f"CogVideoX via ComfyUI (HTTP {r.status_code})"
        except Exception as e: return False, str(e)
    def shutdown(self): pass

def _f2(config): return CogVideoX(config)
registry.register(BackendMeta(name="cogvideox", service_type="video", factory=_f2,
    description="CogVideoX 视频生成（via ComfyUI）", priority=50, tags=["api"]))

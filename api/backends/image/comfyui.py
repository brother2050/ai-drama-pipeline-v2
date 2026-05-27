"""ComfyUI 图片/视频生成 — HTTP API"""
from __future__ import annotations
import json, logging, time, uuid
from pathlib import Path
import httpx
from api.registry import BackendMeta, registry
from infra.http import auth_headers

logger = logging.getLogger(__name__)

class ComfyUI:
    def __init__(self, config: dict):
        self._url = config.get("url", "http://127.0.0.1:8188").rstrip("/")
        self._timeout = config.get("timeouts", {}).get("comfyui", 900)
        self._api_key = config.get("api_key", "")

    @property
    def name(self): return "comfyui"

    def _headers(self) -> dict:
        return auth_headers(self._api_key)

    def upload_image(self, filepath: str, overwrite: bool = True) -> dict:
        """上传图片到 ComfyUI 服务器（用于 IP-Adapter 等需要参考图的节点）"""
        with httpx.Client(timeout=30) as c:
            headers = auth_headers(self._api_key, content_type="")
            with open(filepath, "rb") as f:
                r = c.post(f"{self._url}/upload/image",
                           files={"image": (Path(filepath).name, f)},
                           data={"overwrite": str(overwrite).lower()},
                           headers=headers)
            r.raise_for_status()
            return r.json()

    def generate(self, workflow: dict, output_dir: str) -> list[str]:
        """提交工作流并等待结果，返回生成的文件路径列表"""
        client_id = uuid.uuid4().hex
        with httpx.Client(timeout=self._timeout) as c:
            # 提交
            r = c.post(f"{self._url}/prompt", json={"prompt": workflow, "client_id": client_id},
                      headers=self._headers())
            r.raise_for_status()
            resp = r.json()
            # ComfyUI 提交失败时返回 {"error": "...", "node_errors": {...}}
            if "error" in resp:
                raise RuntimeError(f"ComfyUI 工作流提交失败: {resp['error']}")
            prompt_id = resp.get("prompt_id")
            if not prompt_id:
                raise RuntimeError(f"ComfyUI 未返回 prompt_id: {resp}")

            # 等待完成
            deadline = time.time() + self._timeout
            while time.time() < deadline:
                try:
                    r = c.get(f"{self._url}/history/{prompt_id}")
                    if r.status_code == 200:
                        history = r.json()
                        if prompt_id in history:
                            entry = history[prompt_id]
                            # 检查 ComfyUI 是否报告了任务失败
                            status_info = entry.get("status", {})
                            if status_info.get("status_str") == "error":
                                msgs = status_info.get("messages", [])
                                raise RuntimeError(f"ComfyUI 任务执行失败: {msgs}")
                            outputs = entry.get("outputs", {})
                            if outputs:
                                files = self._download_outputs(c, outputs, output_dir)
                                if not files:
                                    raise RuntimeError("ComfyUI 任务完成但未返回任何文件")
                                return files
                except httpx.HTTPError:
                    pass  # 网络抖动，继续重试
                time.sleep(2)
            raise TimeoutError(f"ComfyUI workflow timeout ({self._timeout}s)")

    def _download_outputs(self, c: httpx.Client, outputs: dict, output_dir: str) -> list[str]:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        files = []
        headers = self._headers()
        for node_out in outputs.values():
            for img in node_out.get("images", []):
                fname = img.get("filename")
                if not fname:
                    continue
                fname = Path(fname).name
                subfolder = Path(img.get("subfolder", "")).name if img.get("subfolder") else ""
                url = f"{self._url}/view?filename={fname}&subfolder={subfolder}&type=output"
                r = c.get(url, headers=headers)
                r.raise_for_status()
                out_path = Path(output_dir) / fname
                out_path.write_bytes(r.content)
                files.append(str(out_path))
        return files

    def health_check(self) -> tuple[bool, str]:
        try:
            with httpx.Client(timeout=5) as c:
                r = c.get(f"{self._url}/system_stats", headers=self._headers())
                return True, f"ComfyUI reachable (HTTP {r.status_code})"
        except Exception as e:
            return False, f"ComfyUI unreachable: {e}"

    def shutdown(self): pass

def _f(config): return ComfyUI(config)
registry.register(BackendMeta(name="comfyui", service_type="image", factory=_f,
    description="ComfyUI 图片/视频生成", priority=10, tags=["api"]))

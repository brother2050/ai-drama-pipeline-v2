"""角色一致性 — IP-Adapter 参考图注入"""
from __future__ import annotations
import json, logging, os, threading
from typing import Any

logger = logging.getLogger(__name__)


class CharacterConsistency:
    """角色一致性管理器"""

    def __init__(self):
        self._cache: dict[str, Any] = {}
        self._lock = threading.Lock()

    def prepare_embedding(self, char_id: str, ref_images: list[str], output_dir: str) -> str:
        """准备角色嵌入（placeholder — 实际由 ComfyUI IP-Adapter 处理）"""
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, f"{char_id}_embedding.json")
        with open(path, "w") as f:
            json.dump({"character_id": char_id, "images": ref_images}, f, indent=2)
        return path

    def build_consistent_workflow(self, char_id: str, ref_images: list[str],
                                   wf: dict, ip_config: dict | None = None) -> dict:
        """注入 IP-Adapter 参考图到工作流"""
        import copy
        wf = copy.deepcopy(wf)
        ip_config = ip_config or {}

        if not ref_images:
            # 移除所有 IP-Adapter 节点（无参考图）
            from engines.workflow import find_nodes_by_class
            for nid in find_nodes_by_class(wf, "IPAdapterAdvanced"):
                del wf[nid]
            return wf

        # 设置参考图到 LoadImage 节点
        from engines.workflow import find_load_image_nodes
        load_nodes = find_load_image_nodes(wf)
        if load_nodes and ref_images:
            wf[load_nodes[0]]["inputs"]["image"] = os.path.basename(ref_images[0])

        # 设置 IP-Adapter 权重
        weight = ip_config.get("weight", 0.6)
        from engines.workflow import apply_ip_adapter_config
        wf = apply_ip_adapter_config(wf, {"weight": weight})

        return wf

    def verify_consistency(self, generated: str, references: list[str], threshold: float = 0.6) -> float:
        """验证一致性分数（placeholder）"""
        return 0.8

    def shutdown(self):
        with self._lock:
            self._cache.clear()

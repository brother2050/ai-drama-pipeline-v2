"""ComfyUI 工作流工具函数 — 节点查找、参数注入"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

__all__ = [
    "find_first_node", "find_nodes_by_class", "find_load_image_nodes",
    "find_character_load_image_nodes", "set_clip_text_prompts",
    "apply_ip_adapter_config", "resolve_node_aliases",
]


def resolve_node_aliases(workflow: dict, available_nodes: set[str]) -> dict:
    if not available_nodes:
        return workflow
    aliases = workflow.pop("_node_aliases", {})
    for nid, node in workflow.items():
        if nid.startswith("_"):
            continue
        ct = node.get("class_type", "")
        if ct in available_nodes:
            continue
        for alt in aliases.get(ct, []):
            if alt in available_nodes:
                node["class_type"] = alt
                logger.info(f"别名: [{nid}] {ct} → {alt}")
                break
    return workflow


def find_first_node(wf: dict, class_type: str) -> str | None:
    for nid, node in wf.items():
        if not nid.startswith("_") and node.get("class_type") == class_type:
            return nid
    return None


def find_nodes_by_class(wf: dict, class_type: str) -> list[str]:
    return [nid for nid, node in wf.items()
            if not nid.startswith("_") and node.get("class_type") == class_type]


def find_load_image_nodes(wf: dict) -> list[str]:
    types = {"LoadImage", "LoadImageFromPath", "ImageLoad"}
    return [nid for nid, node in wf.items()
            if not nid.startswith("_") and node.get("class_type") in types]


def find_character_load_image_nodes(wf: dict) -> list[str]:
    return find_load_image_nodes(wf)


def set_clip_text_prompts(wf: dict, positive: str, negative: str = "", backend: str = "sd15") -> dict:
    for nid, node in wf.items():
        if nid.startswith("_"):
            continue
        if node.get("class_type") == "CLIPTextEncode":
            text = node.get("inputs", {}).get("text", "")
            # 判断是否为 negative prompt 节点：文本较短或包含常见 negative 关键词
            text_lower = text.lower().strip()
            is_negative = (
                len(text_lower) < 20 or
                any(kw in text_lower for kw in ["bad quality", "worst quality", "ugly",
                    "deformed", "blurry", "negative", "low quality", "bad anatomy"])
            )
            if is_negative:
                node["inputs"]["text"] = negative or text
            else:
                node["inputs"]["text"] = positive
    return wf


def apply_ip_adapter_config(wf: dict, config: dict) -> dict:
    weight = config.get("weight", 0.6)
    for nid, node in wf.items():
        if "IPAdapter" in node.get("class_type", ""):
            node.setdefault("inputs", {})["weight"] = weight
    return wf

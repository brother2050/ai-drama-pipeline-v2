"""ComfyUI 工作流工具函数 — 节点查找、参数注入"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

__all__ = [
    "find_first_node", "find_nodes_by_class", "find_load_image_nodes",
    "find_character_load_image_nodes", "find_lora_nodes",
    "find_ip_adapter_nodes", "find_ip_adapter_load_image_nodes",
    "find_pulid_flux_nodes",
    "set_clip_text_prompts",
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
    """查找角色参考图的 LoadImage 节点（IP-Adapter 专用）

    区分角色参考图节点和场景图节点：
    - ipadapter_ref_*: IP-Adapter 主角色参考图
    - ipadapter_ref2_*: IP-Adapter 次要角色参考图
    - char2_load_*: 旧式次要角色参考图

    不包含场景图的 LoadImage 节点。
    """
    all_nodes = find_load_image_nodes(wf)
    # 排除场景图节点（不以 ipadapter_ 或 char2_ 开头的可能是场景图）
    # 但如果只有纯模板（无 IP-Adapter 节点），返回全部 LoadImage
    ipa_nodes = [n for n in all_nodes
                 if n.startswith("ipadapter_ref") or n.startswith("char2_load_")]
    if ipa_nodes:
        return ipa_nodes
    # 模板无 IP-Adapter 节点时，返回全部（向后兼容）
    return all_nodes


def find_ip_adapter_nodes(wf: dict) -> dict[str, list[str]]:
    """查找所有 IP-Adapter 相关节点，按类型分组

    Returns:
        {
            "ipadapter": ["ipadapter_xxx", ...],         # IPAdapterAdvanced
            "model_loader": ["ipadapter_model_xxx", ...], # IPAdapterModelLoader
            "clip_vision": ["ipadapter_clip_vision_xxx", ...], # CLIPVisionLoader
            "ref_images": ["ipadapter_ref_xxx", ...],     # IP-Adapter LoadImage
        }
    """
    result = {"ipadapter": [], "model_loader": [], "clip_vision": [], "ref_images": []}
    for nid, node in wf.items():
        if nid.startswith("_"):
            continue
        ct = node.get("class_type", "")
        if ct == "IPAdapterAdvanced":
            result["ipadapter"].append(nid)
        elif ct == "IPAdapterModelLoader":
            result["model_loader"].append(nid)
        elif ct == "CLIPVisionLoader" and nid.startswith("ipadapter_"):
            result["clip_vision"].append(nid)
        elif ct == "LoadImage" and nid.startswith("ipadapter_ref"):
            result["ref_images"].append(nid)
    return result


def find_ip_adapter_load_image_nodes(wf: dict) -> list[str]:
    """查找 IP-Adapter 专用的 LoadImage 节点（不含场景图）"""
    return [nid for nid, node in wf.items()
            if not nid.startswith("_")
            and node.get("class_type") == "LoadImage"
            and nid.startswith("ipadapter_ref")]


def find_pulid_flux_nodes(wf: dict) -> dict[str, list[str]]:
    """查找所有 PuLID-Flux 相关节点，按类型分组

    Returns:
        {
            "apply": ["pulid_apply_xxx", ...],           # ApplyPuLIDFlux
            "model_loader": ["pulid_model_xxx", ...],    # LoadPuLIDFluxModel
            "insightface": ["pulid_insightface_xxx", ...],# LoadInsightFace
            "eva_clip": ["pulid_eva_clip_xxx", ...],     # LoadEvaClip
            "ref_images": ["pulid_ref_xxx", ...],        # PuLID LoadImage
        }
    """
    result = {"apply": [], "model_loader": [], "insightface": [], "eva_clip": [], "ref_images": []}
    for nid, node in wf.items():
        if nid.startswith("_"):
            continue
        ct = node.get("class_type", "")
        if ct == "ApplyPuLIDFlux":
            result["apply"].append(nid)
        elif ct == "LoadPuLIDFluxModel":
            result["model_loader"].append(nid)
        elif ct == "LoadInsightFace" and nid.startswith("pulid_"):
            result["insightface"].append(nid)
        elif ct == "LoadEvaClip" and nid.startswith("pulid_"):
            result["eva_clip"].append(nid)
        elif ct == "LoadImage" and nid.startswith("pulid_ref"):
            result["ref_images"].append(nid)
    return result


def find_lora_nodes(wf: dict) -> list[tuple[str, str]]:
    """查找工作流中所有 LoRA 加载节点，返回 [(node_id, lora_name), ...]

    支持 LoraLoader 及常见的别名节点类型。
    """
    lora_types = {"LoraLoader", "LoraLoaderModelOnly", "CR Lora Loader"}
    result = []
    for nid, node in wf.items():
        if nid.startswith("_"):
            continue
        if node.get("class_type") in lora_types:
            lora_name = node.get("inputs", {}).get("lora_name", "")
            if lora_name:
                result.append((nid, lora_name))
    return result


def set_clip_text_prompts(wf: dict, positive: str, negative: str = "", backend: str = "sd15") -> dict:
    for nid, node in wf.items():
        if nid.startswith("_"):
            continue
        if node.get("class_type") == "CLIPTextEncode":
            text = node.get("inputs", {}).get("text", "")
            # 判断是否为 negative prompt 节点：文本非空且包含常见 negative 关键词
            # 空文本不作为判断依据（避免误判）
            text_lower = text.lower().strip()
            is_negative = (
                len(text_lower) > 0 and (
                    len(text_lower) < 20 or
                    any(kw in text_lower for kw in ["bad quality", "worst quality", "ugly",
                        "deformed", "blurry", "negative", "low quality", "bad anatomy"])
                )
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

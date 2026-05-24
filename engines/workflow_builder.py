"""ComfyUI 工作流构建器 — 从镜头配置构建可执行工作流

职责:
- 加载 ComfyUI 工作流 JSON 模板
- 构建首帧生成工作流（含多角色 IP-Adapter 链式注入）
- 构建视频生成工作流
- 处理参考图上传映射
"""
from __future__ import annotations
import copy
import json
import logging
import os
from pathlib import Path

from engines.workflow import (
    find_character_load_image_nodes, find_first_node, find_load_image_nodes,
    find_nodes_by_class, resolve_node_aliases, set_clip_text_prompts,
)
from engines.gpu_adapter import get_gpu_config

logger = logging.getLogger(__name__)


class _SimpleContainer:
    """简易容器包装 — 只包装已实例化的后端，供 ensure_portrait 等使用"""
    def __init__(self, image_backend):
        self._image = image_backend
    def get(self, service_type: str, name: str = None):
        if service_type == "image":
            return self._image
        raise ValueError(f"SimpleContainer 不支持: {service_type}")


class WorkflowBuilder:
    """ComfyUI 工作流构建器"""

    def __init__(self, config: dict, models: dict, project_dir: str,
                 wf_dir: str = "", registry=None, comfyui=None):
        self.config = config
        self.models = models
        self.project_dir = project_dir
        self.wf_dir = wf_dir or os.path.join(project_dir, "workflows")
        self.registry = registry
        self.comfyui = comfyui
        self.first_frame_wf: dict = {}
        self.video_wf: dict = {}

    # ── 加载工作流 ──────────────────────────────────────────

    def load_workflows(self) -> None:
        """根据 image_backend / video_backend 加载对应工作流 JSON"""
        available_nodes: set[str] = set()
        if self.comfyui and hasattr(self.comfyui, 'get_available_node_types'):
            try:
                available_nodes = self.comfyui.get_available_node_types()
            except Exception:
                pass

        # 首帧工作流
        img_backend = self.models.get("image_backend", "sd15")
        if self.registry:
            wf_name = self.registry.get_image_workflow(img_backend)
        else:
            wf_name = "01_first_frame_sd15.json" if img_backend != "flux" else "01_first_frame_flux.json"
        self.first_frame_wf = self._load_wf(wf_name)
        self.first_frame_wf = resolve_node_aliases(self.first_frame_wf, available_nodes)

        # 视频工作流
        video_backend = self.models.get("video_backend", "animatediff")
        if self.registry:
            video_wf_name = self.registry.get_video_workflow(video_backend)
        else:
            video_wf_name = "02_img2video.json" if video_backend == "animatediff" else "03_img2video_cogvideo.json"
        self.video_wf = self._load_wf(video_wf_name)
        self.video_wf = resolve_node_aliases(self.video_wf, available_nodes)

        # 应用 GPU 适配
        gpu_cfg = get_gpu_config()
        if self.first_frame_wf:
            self._apply_gpu(self.first_frame_wf, "first_frame", gpu_cfg)
        if self.video_wf:
            self._apply_gpu(self.video_wf, "video", gpu_cfg)

    def _load_wf(self, name: str) -> dict:
        path = os.path.join(self.wf_dir, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        logger.debug(f"工作流不存在: {path}")
        return {}

    def _apply_gpu(self, wf: dict, stage: str, gpu_cfg: dict) -> None:
        """应用 GPU 适配参数到工作流"""
        resolution = gpu_cfg.get("resolution")
        if resolution and len(resolution) == 2:
            for nid, node in wf.items():
                if node.get("class_type") in ("EmptyLatentImage", "EmptySD3LatentImage"):
                    node["inputs"]["width"] = resolution[0]
                    node["inputs"]["height"] = resolution[1]

    # ── 构建首帧工作流 ──────────────────────────────────────

    def build_first_frame(self, shot: dict, character_desc: str = "",
                          scene_desc: str = "", multi_char_prompt: str = "") -> tuple[dict, dict]:
        """构建首帧工作流

        Args:
            shot: 镜头配置
            character_desc: 角色英文描述
            scene_desc: 场景英文描述
            multi_char_prompt: 多角色合并 prompt

        Returns:
            (prompt_dict, workflow_dict) 元组
        """
        from engines.prompt import build_prompt

        # 使用统一的 prompt 构建函数
        style = self.config.get("project", {}).get("style", "cinematic")
        genre = self.config.get("project", {}).get("genre", "urban")
        positive = build_prompt(shot, character_desc=character_desc,
                                scene_desc=scene_desc, style=style, genre=genre)
        if multi_char_prompt:
            positive = f"{positive}, {multi_char_prompt}"

        negative = "bad quality, worst quality, ugly, deformed, blurry, watermark, text"

        prompt = {"positive": positive, "negative": negative}

        # 复制模板工作流
        wf = copy.deepcopy(self.first_frame_wf)
        if not wf:
            return prompt, {}

        # 设置 prompt
        img_backend = self.models.get("image_backend", "sd15")
        set_clip_text_prompts(wf, positive, negative, img_backend)

        # 注入角色参考图（IP-Adapter）
        char_ids = [c.strip() for c in shot.get("characters", "").split("+") if c.strip()]
        ip_config = self.models.get("ip_adapter", {})

        if char_ids:
            wf = self._inject_character_refs(wf, char_ids, ip_config)

        return prompt, wf

    def _inject_character_refs(self, wf: dict, char_ids: list[str],
                                ip_config: dict) -> dict:
        """注入角色参考图到工作流（支持多角色链式 IP-Adapter）"""
        if not char_ids:
            return wf

        # 主角色：使用模板中的 LoadImage 节点
        primary_id = char_ids[0]
        primary_refs = self._get_character_refs(primary_id)
        char_nodes = find_character_load_image_nodes(wf)

        if primary_refs and char_nodes:
            wf[char_nodes[0]]["inputs"]["image"] = os.path.basename(primary_refs[0])
        elif not primary_refs:
            logger.warning(f"角色 '{primary_id}' 无定妆照，IP-Adapter 将使用占位图")

        # 设置 IP-Adapter 权重
        weight = ip_config.get("weight", 0.6)
        for nid in find_nodes_by_class(wf, "IPAdapterAdvanced"):
            if nid in wf:
                wf[nid]["inputs"]["weight"] = weight

        # 第二角色：链式 IP-Adapter
        if len(char_ids) > 1:
            for i, secondary_id in enumerate(char_ids[1:]):
                secondary_refs = self._get_character_refs(secondary_id)
                if secondary_refs:
                    wf = self._add_secondary_ip_adapter(wf, secondary_id, secondary_refs, ip_config, i)

        return wf

    def _add_secondary_ip_adapter(self, wf: dict, char_id: str, ref_images: list[str],
                                    ip_config: dict, index: int = 0) -> dict:
        """为第二角色添加链式 IPAdapterAdvanced 节点"""
        wf = copy.deepcopy(wf)

        # 找现有 IP-Adapter 节点
        ip_nodes = find_nodes_by_class(wf, "IPAdapterAdvanced")
        if not ip_nodes:
            return wf

        primary_ip = ip_nodes[0]

        # 找下游消费者
        downstream_node = None
        downstream_input = None
        for nid, node in wf.items():
            if nid == primary_ip:
                continue
            for inp_name, inp_val in node.get("inputs", {}).items():
                if isinstance(inp_val, list) and len(inp_val) == 2 and inp_val[0] == primary_ip:
                    downstream_node = nid
                    downstream_input = inp_name
                    break
            if downstream_node:
                break

        if not downstream_node:
            downstream_node = find_first_node(wf, "KSampler")
            downstream_input = "model"

        if not downstream_node:
            return wf

        # 创建新节点
        new_load = f"char2_load_{char_id}_{index}"
        new_ip = f"char2_ip_{char_id}_{index}"

        # 计算权重
        primary_weight = float(wf[primary_ip]["inputs"].get("weight", 0.6))
        secondary_weight = ip_config.get("secondary_weight", max(0.3, primary_weight * 0.6))

        # 找 IP-Adapter 模型和 CLIP Vision 节点
        ip_model_node = find_first_node(wf, "IPAdapterModelLoader")
        clip_vision_node = find_first_node(wf, "CLIPVisionLoader")

        # 添加 LoadImage 节点
        wf[new_load] = {"class_type": "LoadImage", "inputs": {"image": os.path.basename(ref_images[0])}}

        # 添加 IPAdapterAdvanced 节点
        ip_inputs = {
            "weight": secondary_weight, "weight_type": "linear",
            "combine_embeds": "concat", "start_at": 0.0, "end_at": 1.0,
            "embeds_scaling": "V only",
            "model": [primary_ip, 0], "image": [new_load, 0],
        }
        if ip_model_node:
            ip_inputs["ipadapter"] = [ip_model_node, 0]
        if clip_vision_node:
            ip_inputs["clip_vision"] = [clip_vision_node, 0]

        wf[new_ip] = {"class_type": "IPAdapterAdvanced", "inputs": ip_inputs}

        # 重接下游
        if downstream_node and downstream_input:
            wf[downstream_node]["inputs"][downstream_input] = [new_ip, 0]

        logger.info(f"添加第二角色 IP-Adapter: {char_id} (weight={secondary_weight:.2f})")
        return wf

    # ── 构建视频工作流 ──────────────────────────────────────

    def build_video(self, frame_path: str) -> dict:
        """构建视频生成工作流"""
        wf = copy.deepcopy(self.video_wf)
        if not wf:
            return {}

        # 设置首帧图
        load_nodes = find_load_image_nodes(wf)
        if load_nodes:
            wf[load_nodes[0]]["inputs"]["image"] = os.path.basename(frame_path)

        return wf

    # ── 参考图上传映射 ──────────────────────────────────────

    def build_upload_map(self, shot: dict, wf: dict) -> dict[str, str]:
        """构建参考图上传映射 {node_id: file_path}"""
        uploads: dict[str, str] = {}
        char_ids = [c.strip() for c in shot.get("characters", "").split("+") if c.strip()]

        char_nodes = find_character_load_image_nodes(wf)
        all_load_nodes = find_load_image_nodes(wf)
        scene_nodes = [n for n in all_load_nodes if n not in set(char_nodes)]

        # 主角色
        if char_ids:
            refs = self._get_character_refs(char_ids[0])
            if refs and char_nodes:
                uploads[char_nodes[0]] = refs[0]

        # 第二角色
        secondary_nodes = [n for n in all_load_nodes if n.startswith("char2_load_")]
        for i, cid in enumerate(char_ids[1:]):
            refs = self._get_character_refs(cid)
            if refs and i < len(secondary_nodes):
                uploads[secondary_nodes[i]] = refs[0]

        # 场景图
        depth_map = shot.get("depth_map", "")
        scene_ref = shot.get("scene_ref", "")
        if depth_map and scene_nodes:
            uploads[scene_nodes[0]] = depth_map
        elif scene_ref and scene_nodes:
            uploads[scene_nodes[0]] = scene_ref

        return uploads

    # ── 内部方法 ──────────────────────────────────────────

    def _get_character_refs(self, char_id: str) -> list[str]:
        """获取角色参考图路径列表"""
        from engines.portrait import ensure_portrait

        # 查找已有定妆照
        char_dir = Path(self.project_dir) / "assets" / "characters" / char_id
        refs = []
        if char_dir.exists():
            for ext in ("*.png", "*.jpg", "*.jpeg"):
                refs.extend(str(p) for p in char_dir.glob(ext))

        if refs:
            return sorted(refs)

        # 尝试自动定妆照（传入简易容器包装 comfyui 实例）
        portrait = ensure_portrait(char_id, self.config,
                                   _SimpleContainer(self.comfyui) if self.comfyui else None)
        if portrait:
            return [portrait]

        # 从 shared_assets 查找
        shared_dir = Path(self.project_dir) / "shared_assets" / "characters" / char_id
        if shared_dir.exists():
            for ext in ("*.png", "*.jpg", "*.jpeg"):
                refs.extend(str(p) for p in shared_dir.glob(ext))

        return sorted(refs)

    def cleanup_dangling_refs(self, wf: dict, removed_ids: list[str]) -> dict:
        """清理工作流中对已删除节点的残留引用"""
        removed_set = set(removed_ids)
        model_source = find_first_node(wf, "UNETLoader") or find_first_node(wf, "CheckpointLoaderSimple")

        for nid, node in list(wf.items()):
            for key, val in list(node.get("inputs", {}).items()):
                if isinstance(val, list) and len(val) == 2 and val[0] in removed_set:
                    if node.get("class_type") == "KSampler" and key == "model" and model_source:
                        node["inputs"][key] = [model_source, 0]
                    else:
                        del node["inputs"][key]

        # 移除缺少必需输入的 IP-Adapter 节点
        changed = True
        while changed:
            changed = False
            current_removed = set()
            for nid, node in list(wf.items()):
                if node.get("class_type") == "IPAdapterAdvanced":
                    img = node.get("inputs", {}).get("image")
                    if not img or (isinstance(img, list) and len(img) == 2 and img[0] not in wf):
                        current_removed.add(nid)
                        del wf[nid]
                        changed = True
            if current_removed:
                removed_set.update(current_removed)
                for nid, node in list(wf.items()):
                    for key, val in list(node.get("inputs", {}).items()):
                        if isinstance(val, list) and len(val) == 2 and val[0] in current_removed:
                            if node.get("class_type") == "KSampler" and key == "model" and model_source:
                                node["inputs"][key] = [model_source, 0]
                            else:
                                del node["inputs"][key]

        return wf

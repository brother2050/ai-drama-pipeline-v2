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
import random
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
                 wf_dir: str = "", registry=None, comfyui=None,
                 force: bool = False):
        self.config = config
        self.models = models
        self.project_dir = project_dir
        self.wf_dir = wf_dir or os.path.join(project_dir, "workflows")
        self.registry = registry
        self.comfyui = comfyui
        self.force = force
        self.first_frame_wf: dict = {}
        self.video_wf: dict = {}

    # ── 加载工作流 ──────────────────────────────────────────

    def load_workflows(self) -> None:
        """根据 image_backend / video_backend 加载对应工作流 JSON"""
        available_nodes: set[str] = set()
        if self.comfyui and hasattr(self.comfyui, 'get_available_node_types'):
            try:
                available_nodes = self.comfyui.get_available_node_types()
            except Exception as e:
                logger.debug(f"获取 ComfyUI 节点类型失败: {e}")

        # 确保 registry 可用（懒加载内置默认）
        if not self.registry:
            from flow.model_registry import ModelRegistry
            self.registry = ModelRegistry(
                os.path.join(self.project_dir, "config", "project.yaml"))

        # 首帧工作流
        img_backend = self.models.get("image_backend", "sd15")
        wf_name = self.registry.get_image_workflow(img_backend)
        if not wf_name:
            logger.warning(f"未知 image_backend '{img_backend}'，回退到 sd15")
            wf_name = self.registry.get_image_workflow("sd15") or "01_first_frame_sd15.json"
        self.first_frame_wf = self._load_wf(wf_name)
        self.first_frame_wf = resolve_node_aliases(self.first_frame_wf, available_nodes)

        # 视频工作流
        video_backend = self.models.get("video_backend", "animatediff")
        video_wf_name = self.registry.get_video_workflow(video_backend)
        if not video_wf_name:
            logger.warning(f"未知 video_backend '{video_backend}'，回退到 animatediff")
            video_wf_name = self.registry.get_video_workflow("animatediff") or "02_img2video.json"
        self.video_wf = self._load_wf(video_wf_name)
        self.video_wf = resolve_node_aliases(self.video_wf, available_nodes)

        # 应用 GPU 适配
        gpu_cfg = get_gpu_config(config=self.config)
        if self.first_frame_wf:
            self._apply_gpu(self.first_frame_wf, "first_frame", gpu_cfg)
        if self.video_wf:
            self._apply_gpu(self.video_wf, "video", gpu_cfg)

    def _load_wf(self, name: str) -> dict:
        path = os.path.join(self.wf_dir, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        # 回退到仓库根目录 workflows/
        root_wf = os.path.join(os.path.dirname(__file__), "..", "workflows", name)
        root_wf = os.path.normpath(root_wf)
        if os.path.exists(root_wf):
            with open(root_wf, encoding="utf-8") as f:
                return json.load(f)
        logger.debug(f"工作流不存在: {path} (也检查了 {root_wf})")
        return {}

    def _apply_gpu(self, wf: dict, stage: str, gpu_cfg: dict) -> None:
        """应用生成参数到工作流（比例自动计算分辨率 + 步数可选覆盖）

        用户配置 generation.aspect_ratio（如 "16:9", "9:16", "1:1"），
        代码读取 JSON 模板的原生分辨率，保持长边不变，按比例计算新分辨率。

        优先级:
          generation.resolution（精确值）> generation.aspect_ratio（比例计算）> JSON 原生值
        """
        resolution = gpu_cfg.get("resolution")
        aspect_ratio = gpu_cfg.get("aspect_ratio")
        image_steps = gpu_cfg.get("image_steps")

        for nid, node in wf.items():
            ct = node.get("class_type", "")
            inp = node.get("inputs", {})

            # 分辨率 → EmptyLatentImage
            if ct in ("EmptyLatentImage", "EmptySD3LatentImage"):
                native_w = inp.get("width", 1024)
                native_h = inp.get("height", 576)

                if resolution and len(resolution) == 2:
                    # 精确值覆盖（最高优先级）
                    inp["width"] = resolution[0]
                    inp["height"] = resolution[1]
                elif aspect_ratio:
                    # 按比例计算：保持长边不变，按比例算短边
                    target_w, target_h = self._calc_resolution(
                        native_w, native_h, aspect_ratio)
                    inp["width"] = target_w
                    inp["height"] = target_h

            # 步数 → KSampler / KSamplerAdvanced（仅首帧）
            if ct in ("KSampler", "KSamplerAdvanced") and stage == "first_frame":
                if image_steps:
                    inp["steps"] = image_steps

        # 视频帧数由 build_video() → _apply_duration() 根据镜头 duration 动态计算，
        # 不再从 generation.video_frames 硬编码读取。

    # ── Seed 随机化 ────────────────────────────────────────

    @staticmethod
    def _calc_resolution(native_w: int, native_h: int, aspect_ratio: str) -> tuple[int, int]:
        """根据目标比例计算分辨率，保持长边不变

        Args:
            native_w: 模板原生宽度
            native_h: 模板原生高度
            aspect_ratio: 目标比例，如 "16:9", "9:16", "1:1", "4:3"

        Returns:
            (width, height) 元组，8 的倍数（模型要求）

        示例（Cosmos 原生 1024×576）：
            "16:9" → 1024×576（不变）
            "9:16" → 576×1024
            "1:1"  → 728×728
        """
        try:
            parts = aspect_ratio.split(":")
            rw, rh = int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            logger.warning(f"无效比例格式: {aspect_ratio}，使用原生分辨率")
            return native_w, native_h

        if rw <= 0 or rh <= 0:
            logger.warning(f"比例值必须为正数: {aspect_ratio}")
            return native_w, native_h

        long_side = max(native_w, native_h)

        if rw >= rh:
            # 横屏或正方形：长边为宽
            w = long_side
            h = int(long_side * rh / rw)
        else:
            # 竖屏：长边为高
            h = long_side
            w = int(long_side * rw / rh)

        # 对齐到 8 的倍数（扩散模型 latent 空间要求）
        w = max(64, (w // 8) * 8)
        h = max(64, (h // 8) * 8)

        logger.info(f"分辨率计算: 原生 {native_w}×{native_h}, 比例 {aspect_ratio} → {w}×{h}")
        return w, h

    @staticmethod
    def _randomize_seed(wf: dict) -> None:
        """随机化工作流中所有 KSampler / KSamplerAdvanced 的 seed，避免重复生成相同图片"""
        for nid, node in wf.items():
            ct = node.get("class_type", "")
            if ct in ("KSampler", "KSamplerAdvanced"):
                node["inputs"]["seed"] = random.randint(0, 2**63 - 1)

    @staticmethod
    def _set_seed(wf: dict, seed: int) -> None:
        """设置指定 seed（用于定妆照三视图/服装图保持一致性）"""
        for nid, node in wf.items():
            ct = node.get("class_type", "")
            if ct in ("KSampler", "KSamplerAdvanced"):
                node["inputs"]["seed"] = seed

    # ── 构建首帧工作流 ──────────────────────────────────────

    def build_first_frame(self, shot: dict, character_desc: str = "",
                          scene_desc: str = "", multi_char_prompt: str = "",
                          seed: int | None = None) -> tuple[dict, dict]:
        """构建首帧工作流

        Args:
            shot: 镜头配置
            character_desc: 角色英文描述
            scene_desc: 场景英文描述
            multi_char_prompt: 多角色合并 prompt
            seed: 指定 seed（None 则随机，用于定妆照一致性控制）

        Returns:
            (prompt_dict, workflow_dict) 元组
        """
        from engines.prompt import build_prompt

        # 使用统一的 prompt 构建函数
        style = self.config.get("project", {}).get("style", "cinematic")
        genre = self.config.get("project", {}).get("genre", "urban")
        img_backend = self.models.get("image_backend", "sd15")
        positive = build_prompt(shot, character_desc=character_desc,
                                scene_desc=scene_desc, style=style, genre=genre,
                                image_backend=img_backend)
        if multi_char_prompt:
            positive = f"{positive}, {multi_char_prompt}"

        negative = ("bad quality, worst quality, ugly, deformed, blurry, "
                    "watermark, text, subtitle, caption, text overlay, "
                    "burned-in text, word, letter, logo, signature, username, timestamp, "
                    "bottom text, top text, screen text, embedded text, "
                    "movie subtitle, film caption, hardcoded subtitle, "
                    "speech bubble, thought bubble, comic text, "
                    "garbled text, corrupted text, misspelled text")

        prompt = {"positive": positive, "negative": negative}

        # 复制模板工作流
        wf = copy.deepcopy(self.first_frame_wf)
        if not wf:
            return prompt, {}

        # 设置 prompt
        img_backend = self.models.get("image_backend", "sd15")
        set_clip_text_prompts(wf, positive, negative, img_backend)

        # 注入角色参考图（IP-Adapter）或 LoRA
        char_ids = [c.strip() for c in shot.get("characters", "").split("+") if c.strip()]
        outfit = shot.get("outfit", "")
        ip_config = self.models.get("ip_adapter", {})

        if char_ids:
            # 为所有角色查找 LoRA，无 LoRA 的用 IP-Adapter 回退
            chars_with_lora = []
            chars_without_lora = []
            for cid in char_ids:
                lora_path = self._find_character_lora(cid)
                if lora_path:
                    chars_with_lora.append((cid, lora_path))
                else:
                    chars_without_lora.append(cid)

            # 注入所有有 LoRA 的角色
            from infra.asset_tracker import comfyui_asset_name
            for cid, lora_path in chars_with_lora:
                lora_strength = self.models.get("character_lora_strength", 0.7)
                name = comfyui_asset_name(self.project_dir, Path(lora_path).stem, Path(lora_path).name)
                wf = self._inject_lora(wf, lora_path, strength=lora_strength, lora_name=name)
                logger.info(f"使用角色 LoRA: {cid} → {lora_path}")

            # 无 LoRA 的角色使用 IP-Adapter 回退
            if chars_without_lora:
                wf = self._inject_character_refs(wf, chars_without_lora, ip_config, outfit=outfit)

        # 注入风格 LoRA（复用上方已读取的 genre）
        if genre:
            style_lora = self._find_style_lora(genre)
            if style_lora:
                style_strength = self.models.get("style_lora_strength", 0.6)
                # 风格 LoRA 用原文件名（用户手动放置，不加 project hash）
                wf = self._inject_lora(wf, style_lora, strength=style_strength,
                                       lora_name=os.path.basename(style_lora))
                logger.info(f"使用风格 LoRA: {genre} → {style_lora}")

        # Seed 控制：指定则用固定 seed（定妆照一致性），否则随机
        if seed is not None:
            self._set_seed(wf, seed)
        else:
            self._randomize_seed(wf)

        return prompt, wf

    def _inject_character_refs(self, wf: dict, char_ids: list[str],
                                ip_config: dict, outfit: str = "") -> dict:
        """注入角色参考图到工作流（支持多角色链式 IP-Adapter）"""
        if not char_ids:
            return wf

        # 主角色：使用模板中的 LoadImage 节点
        primary_id = char_ids[0]
        primary_refs = self._get_character_refs(primary_id, outfit=outfit)
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
                secondary_refs = self._get_character_refs(secondary_id, outfit=outfit)
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

    # ── LoRA 查找与注入 ────────────────────────────────────

    def _find_character_lora(self, char_id: str) -> str | None:
        """查找已训练的角色 LoRA 文件"""
        lora_dir = Path(self.project_dir) / "assets" / "loras"
        from infra.asset_tracker import comfyui_asset_name
        lora_name = comfyui_asset_name(self.project_dir, char_id, f"{char_id}_lora.safetensors")
        candidates = [
            lora_dir / lora_name,                            # proj_{hash}_{char_id}_lora.safetensors
            lora_dir / f"{char_id}_lora.safetensors",        # {char_id}_lora.safetensors（kohya-ss 产出）
            lora_dir / f"{char_id}.safetensors",             # {char_id}.safetensors
        ]
        # 也检查角色目录下的 lora 子目录
        char_dir = Path(self.project_dir) / "assets" / "characters" / char_id / "lora"
        if char_dir.exists():
            for f in char_dir.glob("*.safetensors"):
                candidates.append(f)

        for p in candidates:
            if p.exists():
                return str(p)
        return None

    def _find_style_lora(self, genre: str) -> str | None:
        """查找已训练的风格 LoRA 文件"""
        lora_dir = Path(self.project_dir) / "assets" / "loras"
        candidates = [
            lora_dir / f"style_{genre}_lora.safetensors",
            lora_dir / f"style_{genre}.safetensors",
        ]
        for p in candidates:
            if p.exists():
                return str(p)
        return None

    def _inject_lora(self, wf: dict, lora_path: str, strength: float = 0.7,
                     lora_name: str | None = None) -> dict:
        """向工作流注入 LoRA 加载节点

        在 UNETLoader/CheckpointLoader 之后、KSampler 之前插入 LoraLoader 节点。

        Args:
            lora_name: ComfyUI 服务端的 LoRA 文件名。由调用方决定命名策略：
                - 字符 LoRA: comfyui_asset_name()（带 project hash 防跨项目碰撞）
                - 风格 LoRA: os.path.basename()（用户手动放置，保持原名）
                - None: 回退到 os.path.basename()
        """
        wf = copy.deepcopy(wf)

        # 找模型加载节点（UNETLoader 或 CheckpointLoaderSimple）
        model_source = find_first_node(wf, "UNETLoader") or find_first_node(wf, "CheckpointLoaderSimple")
        if not model_source:
            logger.warning("未找到模型加载节点，无法注入 LoRA")
            return wf

        # 找 KSampler，将 model 输入从 model_source 重接到 LoRA 节点
        ksampler = find_first_node(wf, "KSampler")
        if not ksampler:
            logger.warning("未找到 KSampler 节点，无法注入 LoRA")
            return wf

        # 找 CLIP 来源：CheckpointLoaderSimple 输出 1=clip，否则找 CLIPLoader/CLIPTextEncode
        clip_source = None
        clip_output_idx = 0
        if wf[model_source].get("class_type") == "CheckpointLoaderSimple":
            clip_source = model_source
            clip_output_idx = 1
        else:
            # UNETLoader 不含 clip，找单独的 CLIPLoader
            clip_source = find_first_node(wf, "DualCLIPLoader") or find_first_node(wf, "CLIPLoader")
            if not clip_source:
                # 从 KSampler 的 clip 输入反向追踪来源
                ksampler_clip = wf[ksampler].get("inputs", {}).get("clip")
                if isinstance(ksampler_clip, list) and len(ksampler_clip) == 2:
                    clip_source = ksampler_clip[0]
                else:
                    # 最后手段：找非 CLIPTextEncode 的 CLIP 加载节点
                    clip_loaders = {"CLIPLoader", "DualCLIPLoader", "CLIPVisionLoader"}
                    for nid, node in wf.items():
                        if nid in (model_source, ksampler):
                            continue
                        if node.get("class_type", "") in clip_loaders:
                            clip_source = nid
                            break

        # 创建 LoraLoader 节点（加随机后缀防冲突，如同一角色多次注入）
        lora_node_id = f"lora_{Path(lora_path).stem}_{random.randint(1000, 9999)}"
        # lora_name 由调用方传入（字符 LoRA 用 comfyui_asset_name，风格 LoRA 用 basename）
        if not lora_name:
            lora_name = os.path.basename(lora_path)

        wf[lora_node_id] = {
            "class_type": "LoraLoader",
            "inputs": {
                "lora_name": lora_name,
                "strength_model": strength,
                "strength_clip": strength,
                "model": [model_source, 0],
                "clip": [clip_source, clip_output_idx] if clip_source else [model_source, 0],
            }
        }

        # 将 KSampler 的 model 输入指向 LoRA 节点
        wf[ksampler]["inputs"]["model"] = [lora_node_id, 0]

        logger.info(f"注入 LoRA 节点: {lora_node_id} (strength={strength})")
        return wf

    # ── 构建视频工作流 ──────────────────────────────────────

    def build_video(self, frame_path: str, shot: dict | None = None) -> dict:
        """构建视频生成工作流

        Args:
            frame_path: 首帧图片路径
            shot: 镜头数据（含 duration），用于计算 video_frames
        """
        wf = copy.deepcopy(self.video_wf)
        if not wf:
            return {}

        # 设置首帧图
        load_nodes = find_load_image_nodes(wf)
        if load_nodes:
            wf[load_nodes[0]]["inputs"]["image"] = os.path.basename(frame_path)

        # 根据 duration 动态计算 video_frames（修复 video_frames 与 duration 脱节的问题）
        if shot:
            self._apply_duration(wf, shot)

        # 注入风格 LoRA（视频生成也受益于风格一致性）
        genre = self.config.get("project", {}).get("genre", "")
        if genre:
            style_lora = self._find_style_lora(genre)
            if style_lora:
                style_strength = self.models.get("style_lora_strength", 0.6)
                # 风格 LoRA 用原文件名（用户手动放置，不加 project hash）
                wf = self._inject_lora(wf, style_lora, strength=style_strength,
                                       lora_name=os.path.basename(style_lora))

        # 随机化 seed
        self._randomize_seed(wf)

        return wf

    def _apply_duration(self, wf: dict, shot: dict) -> None:
        """根据镜头 duration 动态调整视频帧数，使生成视频时长匹配分镜预期。

        计算公式: video_frames = max(min_frames, ceil(duration × model_fps))
        不同后端的帧数参数位置不同，按后端类型设置到正确的节点。
        """
        import math

        # 读取 duration（秒），默认 4 秒
        duration = 4
        try:
            duration = int(shot.get("duration", 4))
        except (ValueError, TypeError):
            pass
        duration = max(2, min(8, duration))

        # 获取当前视频后端的 fps
        video_backend = self.models.get("video_backend", "animatediff")
        model_fps = 8  # 默认
        if self.registry:
            defaults = self.registry.get_video_defaults(video_backend)
            if defaults.get("fps"):
                model_fps = defaults["fps"]

        # 计算所需帧数（最少 8 帧，避免过短导致质量问题）
        min_frames = 8
        video_frames = max(min_frames, math.ceil(duration * model_fps))

        logger.info(
            f"视频帧数计算: duration={duration}s × fps={model_fps} → "
            f"video_frames={video_frames} (backend={video_backend})"
        )

        # 按后端类型设置到正确的节点参数
        self._set_video_frames(wf, video_frames, video_backend)

    def _set_video_frames(self, wf: dict, frames: int, backend: str) -> None:
        """根据不同视频后端，将帧数设置到工作流的正确节点。

        后端帧数参数映射:
        - animatediff: ADE_StandardStaticContextOptions.context_length
        - cogvideox: EmptyLatentImage.batch_size
        - cosmos / cosmos-video: CosmosPredict2ImageToVideoLatent.length
        """
        for nid, node in wf.items():
            ct = node.get("class_type", "")
            inp = node.get("inputs", {})

            # AnimateDiff: context_length
            if ct == "ADE_StandardStaticContextOptions" and "context_length" in inp:
                inp["context_length"] = frames
                logger.debug(f"  AnimateDiff: {nid}.context_length = {frames}")

            # CogVideoX: EmptyLatentImage.batch_size（帧数 = batch_size）
            if ct == "EmptyLatentImage" and backend == "cogvideox":
                inp["batch_size"] = frames
                logger.debug(f"  CogVideoX: {nid}.batch_size = {frames}")

            # Cosmos: CosmosPredict2ImageToVideoLatent.length
            if ct == "CosmosPredict2ImageToVideoLatent" and "length" in inp:
                inp["length"] = frames
                logger.debug(f"  Cosmos: {nid}.length = {frames}")

    # ── 参考图上传映射 ──────────────────────────────────────

    def build_upload_map(self, shot: dict, wf: dict) -> dict[str, str]:
        """构建参考图上传映射 {node_id: file_path}"""
        uploads: dict[str, str] = {}
        char_ids = [c.strip() for c in shot.get("characters", "").split("+") if c.strip()]
        outfit = shot.get("outfit", "")

        char_nodes = find_character_load_image_nodes(wf)
        all_load_nodes = find_load_image_nodes(wf)
        scene_nodes = [n for n in all_load_nodes if n not in set(char_nodes)]

        # 主角色
        if char_ids:
            refs = self._get_character_refs(char_ids[0], outfit=outfit)
            if refs and char_nodes:
                uploads[char_nodes[0]] = refs[0]

        # 第二角色
        secondary_nodes = [n for n in all_load_nodes if n.startswith("char2_load_")]
        for i, cid in enumerate(char_ids[1:]):
            refs = self._get_character_refs(cid, outfit=outfit)
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

    def _get_character_refs(self, char_id: str, outfit: str = "") -> list[str]:
        """获取角色参考图路径列表（优先返回 outfit 对应的图）"""
        from engines.portrait import ensure_portrait

        char_dir = Path(self.project_dir) / "assets" / "characters" / char_id

        # 1. 优先查找 outfit 子目录
        if outfit:
            outfit_dir = char_dir / outfit
            refs = []
            if outfit_dir.exists():
                for ext in ("*.png", "*.jpg", "*.jpeg"):
                    refs.extend(str(p) for p in outfit_dir.glob(ext))
            if refs:
                return sorted(refs)

            # outfit 目录为空，尝试触发 ensure_portrait（auto_outfit 会补充 outfit 图）
            portrait = ensure_portrait(char_id, self.config,
                                       _SimpleContainer(self.comfyui) if self.comfyui else None,
                                       force=self.force)
            # 重新检查 outfit 目录
            if outfit_dir.exists():
                for ext in ("*.png", "*.jpg", "*.jpeg"):
                    refs.extend(str(p) for p in outfit_dir.glob(ext))
            if refs:
                return sorted(refs)

        # 2. 回退到角色根目录
        refs = []
        if char_dir.exists():
            for ext in ("*.png", "*.jpg", "*.jpeg"):
                refs.extend(str(p) for p in char_dir.glob(ext))
        if refs:
            return sorted(refs)

        # 3. 尝试自动定妆照（主图也不存在时）
        portrait = ensure_portrait(char_id, self.config,
                                   _SimpleContainer(self.comfyui) if self.comfyui else None,
                                   force=self.force)
        if portrait:
            return [portrait]

        # 4. 从 shared_assets 查找
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

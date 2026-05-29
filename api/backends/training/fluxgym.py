"""FluxGym 训练后端 — 通过 gradio_client 远程调用 FluxGym 训练 LoRA

FluxGym 是 Gradio UI，训练流程分四步：
  1. /load_captioning  — 上传图片 + 自动打标（返回图片路径 + caption）
  2. /create_dataset   — 创建训练数据集（图片 + 150 个 caption 字段）
  3. /update            — 生成训练脚本和配置（返回 train_script + train_config）
  4. /start_training    — 启动训练（需要 base_model + lora_name + train_script + train_config）
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from api.registry import BackendMeta, registry

logger = logging.getLogger(__name__)

__all__ = ["FluxGymTrainer"]

# FluxGym 固定支持的最大图片数
MAX_IMAGES = 150


class FluxGymTrainer:
    """FluxGym 远程 LoRA 训练后端"""

    def __init__(self, config: dict):
        self._api_url = config.get("api_url") or config.get("training", {}).get("api_url", "") or "http://127.0.0.1:7860"
        self._timeout = config.get("timeout", 3600)
        self._poll_interval = config.get("poll_interval", 10)
        # project_dir 必须非空，否则后续 Path 操作会失败
        self._project_dir = config.get("project_dir") or config.get("_project_dir") or ""
        if not self._project_dir:
            logger.warning("FluxGymTrainer: project_dir 为空，下载结果可能失败")
        self._client = None

        # 训练参数默认值（可通过 config 覆盖）
        defaults = config.get("defaults", {})
        self._base_model = defaults.get("base_model", "flux-dev")
        self._resolution = defaults.get("resolution", 512)
        self._steps = defaults.get("steps", 1000)
        self._learning_rate = defaults.get("learning_rate", "8e-4")
        self._network_dim = defaults.get("network_dim", 4)
        self._max_train_epochs = defaults.get("max_train_epochs", 16)
        self._num_repeats = defaults.get("num_repeats", 10)
        self._vram = defaults.get("vram", "20G")

    @property
    def name(self) -> str:
        return "fluxgym"

    def _get_client(self):
        """懒加载 gradio_client"""
        if self._client is None:
            try:
                from gradio_client import Client
                self._client = Client(self._api_url)
            except ImportError:
                raise ImportError(
                    "需要安装 gradio_client: pip install 'ai-drama-pipeline[training]'\n"
                    "或直接: pip install gradio_client"
                )
            except Exception as e:
                raise ConnectionError(f"连接 FluxGym 失败 ({self._api_url}): {e}")
        return self._client

    def _collect_images(self, images_dir: str) -> list[str]:
        """收集目录中的图片文件路径，最多 MAX_IMAGES 张"""
        img_dir = Path(images_dir)
        if not img_dir.exists():
            return []
        paths = []
        for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
            paths.extend(str(p) for p in img_dir.glob(ext))
        paths.sort()
        return paths[:MAX_IMAGES]

    # ── Step 1: 自动打标 ──

    def _load_captioning(self, client, img_paths: list[str],
                         trigger_word: str) -> tuple[list[str], list[str]]:
        """上传图片并自动打标

        Returns:
            (image_paths, captions) — 各 len(img_paths) 个
        """
        from gradio_client import handle_file

        # 构建文件参数
        files = [handle_file(p) for p in img_paths]

        # 调用 /load_captioning（或 /load_captioning_1 等变体）
        api_name = self._find_captioning_api(client)
        logger.info(f"  自动打标: {len(img_paths)} 张图片 (端点: {api_name})")

        result = client.predict(
            files,
            trigger_word,  # concept_sentence
            api_name=api_name,
        )

        # 解析返回: tuple of 300 elements [filepath, str, filepath, str, ...]
        # 偶数位=图片路径, 奇数位=caption
        captions = []
        result_images = []
        for i in range(1, len(result), 2):
            caption = result[i] if i < len(result) else ""
            if caption:
                captions.append(caption)
            img = result[i - 1] if i - 1 >= 0 else ""
            if img:
                result_images.append(img)

        # 补齐不足的 caption
        while len(captions) < len(img_paths):
            captions.append(trigger_word)

        captions = captions[:len(img_paths)]
        result_images = result_images[:len(img_paths)]

        logger.info(f"  打标完成: {len(captions)} 条 caption")
        return result_images, captions

    def _find_captioning_api(self, client) -> str:
        """查找可用的 captioning 端点"""
        try:
            info = client.view_api(return_format="dict")
            endpoints = info.get("named_endpoints", {})
            # 优先 /load_captioning，其次 /run_captioning
            for preferred in ("/load_captioning", "/run_captioning"):
                if preferred in endpoints:
                    return preferred
            # 查找包含 caption 的端点
            for name in endpoints:
                if "caption" in name.lower():
                    return name
        except Exception as e:
            logger.debug(f"API 端点发现失败: {e}")
        return "/load_captioning"

    # ── Step 2: 创建数据集 ──

    def _create_dataset(self, client, img_paths: list[str],
                        captions: list[str],
                        trigger_word: str) -> None:
        """创建训练数据集

        /create_dataset 接受 152 个参数:
          - size (float): 缩放尺寸
          - param_2 (List[filepath]): 图片文件
          - param_3 ~ param_152 (str): Caption 1 ~ Caption 150
        """
        from gradio_client import handle_file

        # 构建图片参数
        files = [handle_file(p) for p in img_paths]

        # 构建 caption 参数: 150 个，不足的用 trigger_word 填充
        caption_args = []
        for i in range(MAX_IMAGES):
            if i < len(captions):
                caption_args.append(captions[i])
            else:
                caption_args.append(trigger_word)

        # 组合参数: [size, files, caption1, caption2, ..., caption150]
        args = [self._resolution] + [files] + caption_args

        logger.info(f"  创建数据集: {len(img_paths)} 张图片, 分辨率 {self._resolution}")
        client.predict(*args, api_name="/create_dataset")
        logger.info("  数据集创建完成")

    # ── Step 3: 生成训练配置 ──

    def _update_config(self, client, trigger_word: str,
                       steps: int, learning_rate: str,
                       rank: int) -> tuple[str, str]:
        """生成训练脚本和配置

        /update 接受 179 个参数，返回 (train_script, train_config)

        关键参数:
          - base_model, lora_name, resolution, seed, workers
          - class_tokens (trigger word), learning_rate, network_dim
          - max_train_epochs, save_every_n_epochs, num_repeats
          - timestep_sampling, guidance_scale, vram
          - ... 以及大量高级参数
        """
        # 计算 epochs: steps = epochs * num_repeats * num_images
        # 这里用用户指定的 steps 反推 epochs
        max_epochs = self._max_train_epochs
        save_epochs = max(1, max_epochs // 4)

        # 构建 /update 的 179 个参数
        # 前 15 个是常用参数，后面 164 个是高级参数（大多用默认值）
        args = [
            self._base_model,           # base_model
            "",                         # lora_name (由 /start_training 传)
            self._resolution,           # resolution
            42,                         # seed
            2,                          # workers
            trigger_word,               # class_tokens
            learning_rate,              # learning_rate
            rank,                       # network_dim (LoRA rank)
            max_epochs,                 # max_train_epochs
            save_epochs,                # save_every_n_epochs
            "shift",                    # timestep_sampling
            1,                          # guidance_scale
            self._vram,                 # vram
            self._num_repeats,          # num_repeats
            "",                         # sample_prompts
        ]

        # 补齐剩余 164 个高级参数（使用默认值）
        # param_16 ~ param_178
        advanced_defaults = self._get_update_advanced_defaults()
        args.extend(advanced_defaults)

        logger.info(f"  生成训练配置: epochs={max_epochs}, lr={learning_rate}, "
                    f"dim={rank}, vram={self._vram}")

        result = client.predict(*args, api_name="/update")

        # 返回 (train_script, train_config)
        if isinstance(result, (list, tuple)) and len(result) >= 2:
            train_script, train_config = result[0], result[1]
            logger.info(f"  训练脚本: {train_script[:80]}...")
            return str(train_script), str(train_config)

        raise RuntimeError(f"/update 返回格式异常: {result}")

    def _get_update_advanced_defaults(self) -> list:
        """获取 /update 端点的高级参数默认值 (param_16 ~ param_178, 共 163 个)"""
        # 按 FluxGym API 文档的默认值填充
        # 格式: [param_16, param_17, ..., param_178]
        defaults = [
            "",     # param_16: --adaptive_noise_scale
            False,  # param_17: --alpha_mask
            False,  # param_18: --apply_t5_attn_mask
            False,  # param_19: --async_upload
            "",     # param_20: --base_weights
            "",     # param_21: --base_weights_multiplier
            False,  # param_22: --bucket_no_upscale
            "",     # param_23: --bucket_reso_steps
            False,  # param_24: --cache_info
            False,  # param_25: --cache_latents
            "",     # param_26: --caption_dropout_every_n_epochs
            "",     # param_27: --caption_dropout_rate
            "",     # param_28: --caption_extension
            "",     # param_29: --caption_extention
            "",     # param_30: --caption_prefix
            "",     # param_31: --caption_separator
            "",     # param_32: --caption_suffix
            "",     # param_33: --caption_tag_dropout_rate
            "",     # param_34: --clip_skip
            False,  # param_35: --color_aug
            "",     # param_36: --conditioning_data_dir
            "",     # param_37: --config_file
            "",     # param_38: --console_log_file
            "",     # param_39: --console_log_level
            False,  # param_40: --console_log_simple
            "",     # param_41: --controlnet_model_name_or_path
            False,  # param_42: --cpu_offload_checkpointing
            "",     # param_43: --dataset_class
            "",     # param_44: --dataset_repeats
            False,  # param_45: --ddp_gradient_as_bucket_view
            False,  # param_46: --ddp_static_graph
            "",     # param_47: --ddp_timeout
            False,  # param_48: --debiased_estimation_loss
            False,  # param_49: --debug_dataset
            False,  # param_50: --deepspeed
            False,  # param_51: --dim_from_weights
            "",     # param_52: --dynamo_backend
            False,  # param_53: --enable_bucket
            False,  # param_54: --enable_wildcard
            "",     # param_55: --face_crop_aug_range
            False,  # param_56: --flip_aug
            False,  # param_57: --fp16_master_weights_and_gradients
            False,  # param_58: --fp8_base_unet
            False,  # param_59: --full_bf16
            False,  # param_60: --full_fp16
            False,  # param_61: --fused_backward_pass
            "",     # param_62: --gradient_accumulation_steps
            "",     # param_63: --huber_c
            "",     # param_64: --huber_scale
            "",     # param_65: --huber_schedule
            "",     # param_66: --huggingface_path_in_repo
            "",     # param_67: --huggingface_repo_id
            "",     # param_68: --huggingface_repo_type
            "",     # param_69: --huggingface_repo_visibility
            "",     # param_70: --huggingface_token
            "",     # param_71: --in_json
            "",     # param_72: --initial_epoch
            "",     # param_73: --initial_step
            "",     # param_74: --ip_noise_gamma
            False,  # param_75: --ip_noise_gamma_random_strength
            "",     # param_76: --keep_tokens
            "",     # param_77: --keep_tokens_separator
            False,  # param_78: --log_config
            "",     # param_79: --log_prefix
            "",     # param_80: --log_tracker_config
            "",     # param_81: --log_tracker_name
            "",     # param_82: --log_with
            "",     # param_83: --logging_dir
            False,  # param_84: --lowram
            "",     # param_85: --lr_decay_steps
            "",     # param_86: --lr_scheduler_args
            "",     # param_87: --lr_scheduler_min_lr_ratio
            "",     # param_88: --lr_scheduler_num_cycles
            "",     # param_89: --lr_scheduler_power
            "",     # param_90: --lr_scheduler_timescale
            "",     # param_91: --lr_scheduler_type
            "",     # param_92: --lr_warmup_steps
            False,  # param_93: --masked_loss
            "",     # param_94: --max_bucket_reso
            "",     # param_95: --max_timestep
            "",     # param_96: --max_token_length
            "",     # param_97: --max_train_steps
            "",     # param_98: --max_validation_steps
            False,  # param_99: --mem_eff_attn
            "",     # param_100: --metadata_author
            "",     # param_101: --metadata_description
            "",     # param_102: --metadata_license
            "",     # param_103: --metadata_tags
            "",     # param_104: --metadata_title
            "",     # param_105: --min_bucket_reso
            "",     # param_106: --min_snr_gamma
            "",     # param_107: --min_timestep
            "",     # param_108: --multires_noise_discount
            "",     # param_109: --multires_noise_iterations
            "",     # param_110: --network_alpha
            "",     # param_111: --network_dropout
            False,  # param_112: --network_train_text_encoder_only
            False,  # param_113: --network_train_unet_only
            "",     # param_114: --network_weights
            False,  # param_115: --no_half_vae
            False,  # param_116: --no_metadata
            "",     # param_117: --noise_offset
            False,  # param_118: --noise_offset_random_strength
            "",     # param_119: --offload_optimizer_device
            "",     # param_120: --offload_optimizer_nvme_path
            "",     # param_121: --offload_param_device
            "",     # param_122: --offload_param_nvme_path
            False,  # param_123: --output_config
            "",     # param_124: --prior_loss_weight
            False,  # param_125: --random_crop
            "",     # param_126: --reg_data_dir
            "",     # param_127: --resize_interpolation
            "",     # param_128: --resolution
            "",     # param_129: --resume
            False,  # param_130: --resume_from_huggingface
            False,  # param_131: --sample_at_first
            "",     # param_132: --sample_every_n_epochs
            "",     # param_133: --sample_sampler
            "",     # param_134: --save_every_n_steps
            "",     # param_135: --save_last_n_epochs
            "",     # param_136: --save_last_n_epochs_state
            "",     # param_137: --save_last_n_steps
            "",     # param_138: --save_last_n_steps_state
            "",     # param_139: --save_n_epoch_ratio
            False,  # param_140: --save_state
            False,  # param_141: --save_state_on_train_end
            False,  # param_142: --save_state_to_huggingface
            False,  # param_143: --scale_v_pred_loss_like_noise_pred
            "",     # param_144: --scale_weight_norms
            "",     # param_145: --secondary_separator
            False,  # param_146: --shuffle_caption
            "",     # param_147: --sigmoid_scale
            False,  # param_148: --skip_cache_check
            False,  # param_149: --skip_until_initial_step
            "",     # param_150: --t5xxl_max_token_length
            "",     # param_151: --text_encoder_lr
            "",     # param_152: --token_warmup_min
            "",     # param_153: --token_warmup_step
            "",     # param_154: --tokenizer_cache_dir
            False,  # param_155: --torch_compile
            "",     # param_156: --train_batch_size
            "",     # param_157: --train_data_dir
            "",     # param_158: --training_comment
            "",     # param_159: --unet_lr
            False,  # param_160: --use_8bit_adam
            False,  # param_161: --use_lion_optimizer
            False,  # param_162: --v2
            False,  # param_163: --v_parameterization
            "",     # param_164: --v_pred_like_loss
            "",     # param_165: --vae
            "",     # param_166: --vae_batch_size
            "",     # param_167: --validate_every_n_epochs
            "",     # param_168: --validate_every_n_steps
            "",     # param_169: --validation_seed
            "",     # param_170: --validation_split
            "",     # param_171: --wandb_api_key
            "",     # param_172: --wandb_run_name
            False,  # param_173: --weighted_captions
            False,  # param_174: --xformers
            False,  # param_175: --zero3_init_flag
            False,  # param_176: --zero3_save_16bit_model
            "",     # param_177: --zero_stage
            False,  # param_178: --zero_terminal_snr
        ]
        return defaults

    # ── Step 4: 启动训练 ──

    def _start_training(self, client, base_model: str,
                        lora_name: str, train_script: str,
                        train_config: str,
                        sample_prompts: str = "") -> Any:
        """启动 LoRA 训练

        /start_training 参数:
          - base_model: flux-dev / flux-schnell / bdsqlsz/flux1-dev2pro-single
          - lora_name: LoRA 名称
          - train_script: /update 返回的训练脚本
          - train_config: /update 返回的训练配置
          - sample_prompts: 采样提示词（可选）
        """
        logger.info(f"  启动训练: {lora_name} (base: {base_model})")

        result = client.predict(
            base_model,
            lora_name,
            train_script,
            train_config,
            sample_prompts,
            api_name="/start_training",
        )

        logger.info("  训练已启动")
        return result

    # ── 主入口 ──

    def train_lora(self, char_id: str, images_dir: str, *,
                   trigger_word: str = "",
                   steps: int = 1000,
                   learning_rate: float = 1e-4,
                   rank: int = 16,
                   resolution: str = "512x768",
                   output_name: str = "") -> str:
        """训练角色 LoRA（完整四步流程）

        Args:
            char_id: 角色 ID
            images_dir: 训练图片目录
            trigger_word: 触发词（如 ohwx person）
            steps: 训练步数
            learning_rate: 学习率
            rank: LoRA rank (network_dim)
            resolution: 训练分辨率（如 "512x768"）
            output_name: 输出文件名（默认 {char_id}_lora）

        Returns:
            训练后的本地 .safetensors 路径
        """
        if not output_name:
            output_name = f"{char_id}_lora"
        if not trigger_word:
            trigger_word = f"ohwx {char_id}"

        # 解析分辨率（取第一个数值作为 FluxGym 的 size 参数）
        try:
            res_val = int(resolution.split("x")[0]) if "x" in str(resolution) else int(resolution)
        except (ValueError, AttributeError):
            res_val = self._resolution

        # 收集训练图片
        img_paths = self._collect_images(images_dir)
        if not img_paths:
            raise FileNotFoundError(f"训练图片目录为空: {images_dir}")

        # 验证图片路径有效性（gradio_client handle_file 会 stat 文件）
        valid_paths = []
        for p in img_paths:
            try:
                if p and Path(p).exists():
                    valid_paths.append(p)
                else:
                    logger.warning(f"  跳过无效图片路径: {p}")
            except (TypeError, OSError):
                logger.warning(f"  跳过无效图片路径: {p}")
        if not valid_paths:
            raise FileNotFoundError(f"训练图片目录中无有效图片: {images_dir}")
        img_paths = valid_paths

        logger.info(f"开始训练 LoRA: {char_id}, 图片 {len(img_paths)} 张, "
                    f"steps={steps}, rank={rank}")

        client = self._get_client()

        # Step 1: 自动打标
        logger.info("[1/4] 自动打标...")
        _, captions = self._load_captioning(client, img_paths, trigger_word)

        # Step 2: 创建数据集
        logger.info("[2/4] 创建数据集...")
        # 临时覆盖 resolution
        old_res = self._resolution
        self._resolution = res_val
        try:
            self._create_dataset(client, img_paths, captions, trigger_word)
        finally:
            self._resolution = old_res

        # Step 3: 生成训练配置
        logger.info("[3/4] 生成训练配置...")
        lr_str = str(learning_rate) if isinstance(learning_rate, float) else learning_rate
        train_script, train_config = self._update_config(
            client, trigger_word, steps, lr_str, rank,
        )

        # Step 4: 启动训练
        logger.info("[4/4] 启动训练...")
        result = self._start_training(
            client, self._base_model, output_name,
            train_script, train_config,
        )

        # 下载结果
        lora_path = self._download_result(result, char_id)
        logger.info(f"LoRA 训练完成: {lora_path}")
        return lora_path

    def train_style_lora(self, genre: str, images_dir: str, *,
                         trigger_word: str = "",
                         steps: int = 1000,
                         rank: int = 16,
                         output_name: str = "") -> str:
        """训练风格 LoRA"""
        if not output_name:
            output_name = f"style_{genre}_lora"
        if not trigger_word:
            trigger_word = f"{genre} style"

        img_paths = self._collect_images(images_dir)
        if not img_paths:
            raise FileNotFoundError(f"风格图片目录为空: {images_dir}")

        logger.info(f"开始训练风格 LoRA: {genre}, 图片 {len(img_paths)} 张")

        client = self._get_client()

        # Step 1-2: 打标 + 创建数据集
        _, captions = self._load_captioning(client, img_paths, trigger_word)
        self._create_dataset(client, img_paths, captions, trigger_word)

        # Step 3-4: 生成配置 + 训练
        train_script, train_config = self._update_config(
            client, trigger_word, steps, self._learning_rate, rank,
        )
        result = self._start_training(
            client, self._base_model, output_name,
            train_script, train_config,
        )

        return self._download_result(result, f"style_{genre}")

    def check_status(self) -> dict:
        """检查 FluxGym 服务状态"""
        try:
            client = self._get_client()
            info = client.view_api(return_format="dict")
            endpoints = list(info.get("named_endpoints", {}).keys())
            return {
                "status": "connected",
                "url": self._api_url,
                "endpoints": endpoints,
                "endpoint_count": len(endpoints),
            }
        except Exception as e:
            return {"status": "disconnected", "url": self._api_url, "error": str(e)}

    def _download_result(self, result: Any, prefix: str) -> str:
        """下载训练结果到本地 assets 目录

        Args:
            result: FluxGym 返回的结果（训练日志列表或路径）
            prefix: 文件名前缀

        Returns:
            本地 .safetensors 路径
        """
        import shutil

        if not self._project_dir:
            raise RuntimeError(
                "FluxGymTrainer: project_dir 为空，无法下载结果。"
                "请在 config/system.yaml 中配置 training.api_url"
            )

        output_dir = Path(self._project_dir) / "assets" / "loras"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{prefix}.safetensors"

        lora_name = f"{prefix}_lora" if not prefix.endswith("_lora") else prefix

        # ── 1. 尝试从 FluxGym 本地输出目录获取 ──
        possible_paths = [
            Path(f"/workspace/fluxgym/outputs/{lora_name}"),
            Path(f"/workspace/fluxgym/outputs/{prefix}"),
            Path.home() / "fluxgym" / "outputs" / lora_name,
        ]

        for base in possible_paths:
            try:
                if base.exists():
                    for safetensor in base.glob("**/*.safetensors"):
                        shutil.copy2(str(safetensor), str(output_path))
                        logger.info(f"  从 FluxGym 输出目录复制: {safetensor}")
                        return str(output_path)
            except (TypeError, OSError) as e:
                logger.debug(f"  检查路径 {base} 失败: {e}")
                continue

        # ── 2. 从 result 中提取路径或 URL ──
        candidates = []
        if isinstance(result, str) and result:
            candidates.append(result)
        elif isinstance(result, (list, tuple)):
            for item in result:
                if isinstance(item, str) and item:
                    candidates.append(item)

        for item in candidates:
            # 本地文件路径
            try:
                p = Path(item)
                if p.exists() and p.suffix == ".safetensors":
                    shutil.copy2(str(p), str(output_path))
                    return str(output_path)
            except (TypeError, OSError):
                pass
            # URL
            if item.startswith("http") and ".safetensors" in item:
                try:
                    import httpx
                    resp = httpx.get(item, timeout=120)
                    resp.raise_for_status()
                    output_path.write_bytes(resp.content)
                    return str(output_path)
                except Exception as e:
                    logger.debug(f"  下载 URL 失败: {e}")

        # ── 3. 无法自动获取，返回预期路径（训练可能仍在进行） ──
        logger.warning(
            f"  无法自动获取 LoRA 文件。训练已在 FluxGym 服务器上启动。\n"
            f"  训练完成后，请将 .safetensors 复制到: {output_path}\n"
            f"  FluxGym 输出目录: /workspace/fluxgym/outputs/{lora_name}/"
        )
        return str(output_path)

    def get_samples(self, lora_name: str) -> list[dict]:
        """获取训练样本预览

        调用 /get_samples 端点获取训练过程中的样本图片
        """
        client = self._get_client()
        try:
            result = client.predict(lora_name, api_name="/get_samples")
            if isinstance(result, list):
                return [{"image": item.get("image", ""), "caption": item.get("caption")}
                        for item in result if isinstance(item, dict)]
        except Exception as e:
            logger.debug(f"获取样本失败: {e}")
        return []

    def shutdown(self):
        """关闭连接"""
        self._client = None


# ── 注册到全局注册表 ──────────────────────────────────────

registry.register(BackendMeta(
    name="fluxgym",
    service_type="training",
    factory=lambda cfg: FluxGymTrainer(cfg),
    description="FluxGym 远程 LoRA 训练（Gradio API）",
    priority=10,
    tags=["lora", "training", "flux", "gradio"],
))

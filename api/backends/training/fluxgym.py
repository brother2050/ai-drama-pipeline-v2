"""FluxGym 训练后端 — 通过 gradio_client 远程调用 FluxGym 训练 LoRA

FluxGym Gradio API 四步流程:
  1. /load_captioning  — 上传图片 + 自动打标
  2. /create_dataset   — 创建训练数据集
  3. /update            — 生成训练脚本和配置
  4. /start_training    — 启动训练

API 文档: 参见项目根目录 k.txt
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from api.registry import BackendMeta, registry

logger = logging.getLogger(__name__)

__all__ = ["FluxGymTrainer"]

MAX_IMAGES = 150  # FluxGym 固定最大图片数


class FluxGymTrainer:
    """FluxGym 远程 LoRA 训练后端"""

    def __init__(self, config: dict):
        self._api_url = (config.get("api_url")
                         or config.get("training", {}).get("api_url", "")
                         or "http://127.0.0.1:7860")
        self._timeout = config.get("timeout", 3600)
        self._poll_interval = config.get("poll_interval", 10)
        self._project_dir = config.get("project_dir") or config.get("_project_dir") or ""
        if not self._project_dir:
            logger.warning("FluxGymTrainer: project_dir 为空，下载结果可能失败")
        self._client = None

        # 训练参数默认值
        defaults = config.get("defaults", {})
        self._base_model = defaults.get("base_model", "flux-dev")
        self._default_resolution = defaults.get("resolution", 512)
        self._default_learning_rate = str(defaults.get("learning_rate", "8e-4"))
        self._default_network_dim = defaults.get("network_dim", 4)
        self._default_max_train_epochs = defaults.get("max_train_epochs", 16)
        self._default_num_repeats = defaults.get("num_repeats", 10)
        self._default_vram = defaults.get("vram", "20G")

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
                    "需要安装 gradio_client: pip install 'ai-drama-pipeline[training]'")
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

    def _validate_paths(self, img_paths: list[str]) -> list[str]:
        """验证图片路径有效性，过滤无效路径"""
        valid = []
        for p in img_paths:
            if not p:
                continue
            try:
                if Path(p).exists():
                    valid.append(p)
                else:
                    logger.warning(f"  跳过不存在的图片: {p}")
            except (TypeError, OSError) as e:
                logger.warning(f"  跳过无效路径 {p}: {e}")
        return valid

    # ────────────────────────────────────────────────
    # Step 1: /load_captioning — 上传图片 + 自动打标
    # ────────────────────────────────────────────────

    def _load_captioning(self, client, img_paths: list[str],
                         trigger_word: str) -> list[str]:
        """上传图片并自动打标

        API: /load_captioning
          参数: uploaded_files (List[filepath]), concept_sentence (str)
          返回: tuple of 300 elements — [filepath, str, filepath, str, ...]
                偶数位=图片路径, 奇数位=caption

        Returns:
            captions 列表，长度 = len(img_paths)
        """
        from gradio_client import handle_file

        files = []
        for p in img_paths:
            try:
                files.append(handle_file(p))
            except Exception as e:
                logger.warning(f"  handle_file 失败 ({p}): {e}")

        if not files:
            raise RuntimeError("无有效图片文件可供上传")

        # 查找可用端点
        api_name = self._find_api(client, "caption", "/load_captioning")
        logger.info(f"  自动打标: {len(files)} 张图片 (端点: {api_name})")

        result = client.predict(
            uploaded_files=files,
            concept_sentence=trigger_word,
            api_name=api_name,
        )

        # 解析返回: [img0, cap0, img1, cap1, ...]
        captions = []
        for i in range(1, len(result), 2):
            cap = result[i] if i < len(result) else ""
            captions.append(cap if cap else trigger_word)

        # 补齐/截断
        while len(captions) < len(img_paths):
            captions.append(trigger_word)
        captions = captions[:len(img_paths)]

        logger.info(f"  打标完成: {len(captions)} 条 caption")
        return captions

    # ────────────────────────────────────────────────
    # Step 2: /create_dataset — 创建训练数据集
    # ────────────────────────────────────────────────

    def _create_dataset(self, client, img_paths: list[str],
                        captions: list[str], resolution: int) -> None:
        """创建训练数据集

        API: /create_dataset
          参数 (152个):
            - size (float): 缩放尺寸
            - param_2 (List[filepath]): 图片文件列表
            - param_3 ~ param_152 (str): Caption 1 ~ Caption 150
        """
        from gradio_client import handle_file

        files = []
        for p in img_paths:
            try:
                files.append(handle_file(p))
            except Exception as e:
                logger.warning(f"  handle_file 失败 ({p}): {e}")

        if not files:
            raise RuntimeError("无有效图片文件用于创建数据集")

        # 150 个 caption 参数，不足用 trigger_word 填充
        trigger = captions[0] if captions else ""
        caption_args = []
        for i in range(MAX_IMAGES):
            caption_args.append(captions[i] if i < len(captions) else trigger)

        # /create_dataset 参数: size, files, cap1, cap2, ..., cap150
        args = [resolution, files] + caption_args

        logger.info(f"  创建数据集: {len(img_paths)} 张图, {resolution}px")
        client.predict(*args, api_name="/create_dataset")
        logger.info("  数据集创建完成")

    # ────────────────────────────────────────────────
    # Step 3: /update — 生成训练脚本和配置
    # ────────────────────────────────────────────────

    def _update_config(self, client, trigger_word: str, lora_name: str,
                       steps: int, learning_rate: str, rank: int,
                       resolution: int) -> tuple[str, str]:
        """生成训练脚本和配置

        API: /update
          参数 (179个):
            命名参数 (15个):
              base_model, lora_name, resolution, seed, workers,
              class_tokens, learning_rate, network_dim,
              max_train_epochs, save_every_n_epochs,
              timestep_sampling, guidance_scale, vram,
              num_repeats, sample_prompts
            高级参数 (164个):
              param_16 ~ param_178

          返回: tuple of 2 — (train_script, train_config)
        """
        max_epochs = self._default_max_train_epochs
        save_epochs = max(1, max_epochs // 4)

        # ── 15 个命名参数（按文档顺序，用关键字传递） ──
        args = [
            self._base_model,           # base_model
            lora_name,                  # lora_name (必须非空！影响脚本路径)
            resolution,                 # resolution
            42,                         # seed
            2,                          # workers
            trigger_word,               # class_tokens
            learning_rate,              # learning_rate
            rank,                       # network_dim
            max_epochs,                 # max_train_epochs
            save_epochs,                # save_every_n_epochs
            "shift",                    # timestep_sampling
            1,                          # guidance_scale
            self._default_vram,         # vram
            self._default_num_repeats,  # num_repeats
            "",                         # sample_prompts
        ]

        # ── 164 个高级参数 (param_16 ~ param_178) ──
        args.extend(self._advanced_defaults())

        logger.info(f"  生成训练配置: epochs={max_epochs}, lr={learning_rate}, "
                    f"dim={rank}, vram={self._default_vram}")
        logger.debug(f"  /update 参数数: {len(args)} (应为 179)")

        result = client.predict(*args, api_name="/update")

        if isinstance(result, (list, tuple)) and len(result) >= 2:
            logger.info(f"  训练脚本已生成")
            return str(result[0]), str(result[1])

        raise RuntimeError(f"/update 返回格式异常: {type(result)} {result}")

    @staticmethod
    def _advanced_defaults() -> list:
        """/update 的 164 个高级参数默认值 (param_16 ~ param_178)

        按 FluxGym API 文档严格对应:
          param_16  = --adaptive_noise_scale (str)
          param_17  = --alpha_mask (bool)
          ...
          param_178 = --zero_terminal_snr (bool)
        """
        return [
            "",     # 16  --adaptive_noise_scale
            False,  # 17  --alpha_mask
            False,  # 18  --apply_t5_attn_mask
            False,  # 19  --async_upload
            "",     # 20  --base_weights
            "",     # 21  --base_weights_multiplier
            False,  # 22  --bucket_no_upscale
            "",     # 23  --bucket_reso_steps
            False,  # 24  --cache_info
            False,  # 25  --cache_latents
            "",     # 26  --caption_dropout_every_n_epochs
            "",     # 27  --caption_dropout_rate
            "",     # 28  --caption_extension
            "",     # 29  --caption_extention
            "",     # 30  --caption_prefix
            "",     # 31  --caption_separator
            "",     # 32  --caption_suffix
            "",     # 33  --caption_tag_dropout_rate
            "",     # 34  --clip_skip
            False,  # 35  --color_aug
            "",     # 36  --conditioning_data_dir
            "",     # 37  --config_file
            "",     # 38  --console_log_file
            "",     # 39  --console_log_level
            False,  # 40  --console_log_simple
            "",     # 41  --controlnet_model_name_or_path
            False,  # 42  --cpu_offload_checkpointing
            "",     # 43  --dataset_class
            "",     # 44  --dataset_repeats
            False,  # 45  --ddp_gradient_as_bucket_view
            False,  # 46  --ddp_static_graph
            "",     # 47  --ddp_timeout
            False,  # 48  --debiased_estimation_loss
            False,  # 49  --debug_dataset
            False,  # 50  --deepspeed
            False,  # 51  --dim_from_weights
            "",     # 52  --dynamo_backend
            False,  # 53  --enable_bucket
            False,  # 54  --enable_wildcard
            "",     # 55  --face_crop_aug_range
            False,  # 56  --flip_aug
            False,  # 57  --fp16_master_weights_and_gradients
            False,  # 58  --fp8_base_unet
            False,  # 59  --full_bf16
            False,  # 60  --full_fp16
            False,  # 61  --fused_backward_pass
            "",     # 62  --gradient_accumulation_steps
            "",     # 63  --huber_c
            "",     # 64  --huber_scale
            "",     # 65  --huber_schedule
            "",     # 66  --huggingface_path_in_repo
            "",     # 67  --huggingface_repo_id
            "",     # 68  --huggingface_repo_type
            "",     # 69  --huggingface_repo_visibility
            "",     # 70  --huggingface_token
            "",     # 71  --in_json
            "",     # 72  --initial_epoch
            "",     # 73  --initial_step
            "",     # 74  --ip_noise_gamma
            False,  # 75  --ip_noise_gamma_random_strength
            "",     # 76  --keep_tokens
            "",     # 77  --keep_tokens_separator
            False,  # 78  --log_config
            "",     # 79  --log_prefix
            "",     # 80  --log_tracker_config
            "",     # 81  --log_tracker_name
            "",     # 82  --log_with
            "",     # 83  --logging_dir
            False,  # 84  --lowram
            "",     # 85  --lr_decay_steps
            "",     # 86  --lr_scheduler_args
            "",     # 87  --lr_scheduler_min_lr_ratio
            "",     # 88  --lr_scheduler_num_cycles
            "",     # 89  --lr_scheduler_power
            "",     # 90  --lr_scheduler_timescale
            "",     # 91  --lr_scheduler_type
            "",     # 92  --lr_warmup_steps
            False,  # 93  --masked_loss
            "",     # 94  --max_bucket_reso
            "",     # 95  --max_timestep
            "",     # 96  --max_token_length
            "",     # 97  --max_train_steps
            "",     # 98  --max_validation_steps
            False,  # 99  --mem_eff_attn
            "",     # 100 --metadata_author
            "",     # 101 --metadata_description
            "",     # 102 --metadata_license
            "",     # 103 --metadata_tags
            "",     # 104 --metadata_title
            "",     # 105 --min_bucket_reso
            "",     # 106 --min_snr_gamma
            "",     # 107 --min_timestep
            "",     # 108 --multires_noise_discount
            "",     # 109 --multires_noise_iterations
            "",     # 110 --network_alpha
            "",     # 111 --network_dropout
            False,  # 112 --network_train_text_encoder_only
            False,  # 113 --network_train_unet_only
            "",     # 114 --network_weights
            False,  # 115 --no_half_vae
            False,  # 116 --no_metadata
            "",     # 117 --noise_offset
            False,  # 118 --noise_offset_random_strength
            "",     # 119 --offload_optimizer_device
            "",     # 120 --offload_optimizer_nvme_path
            "",     # 121 --offload_param_device
            "",     # 122 --offload_param_nvme_path
            False,  # 123 --output_config
            "",     # 124 --prior_loss_weight
            False,  # 125 --random_crop
            "",     # 126 --reg_data_dir
            "",     # 127 --resize_interpolation
            "",     # 128 --resolution
            "",     # 129 --resume
            False,  # 130 --resume_from_huggingface
            False,  # 131 --sample_at_first
            "",     # 132 --sample_every_n_epochs
            "",     # 133 --sample_sampler
            "",     # 134 --save_every_n_steps
            "",     # 135 --save_last_n_epochs
            "",     # 136 --save_last_n_epochs_state
            "",     # 137 --save_last_n_steps
            "",     # 138 --save_last_n_steps_state
            "",     # 139 --save_n_epoch_ratio
            False,  # 140 --save_state
            False,  # 141 --save_state_on_train_end
            False,  # 142 --save_state_to_huggingface
            False,  # 143 --scale_v_pred_loss_like_noise_pred
            "",     # 144 --scale_weight_norms
            "",     # 145 --secondary_separator
            False,  # 146 --shuffle_caption
            "",     # 147 --sigmoid_scale
            False,  # 148 --skip_cache_check
            False,  # 149 --skip_until_initial_step
            "",     # 150 --t5xxl_max_token_length
            "",     # 151 --text_encoder_lr
            "",     # 152 --token_warmup_min
            "",     # 153 --token_warmup_step
            "",     # 154 --tokenizer_cache_dir
            False,  # 155 --torch_compile
            "",     # 156 --train_batch_size
            "",     # 157 --train_data_dir
            "",     # 158 --training_comment
            "",     # 159 --unet_lr
            False,  # 160 --use_8bit_adam
            False,  # 161 --use_lion_optimizer
            False,  # 162 --v2
            False,  # 163 --v_parameterization
            "",     # 164 --v_pred_like_loss
            "",     # 165 --vae
            "",     # 166 --vae_batch_size
            "",     # 167 --validate_every_n_epochs
            "",     # 168 --validate_every_n_steps
            "",     # 169 --validation_seed
            "",     # 170 --validation_split
            "",     # 171 --wandb_api_key
            "",     # 172 --wandb_run_name
            False,  # 173 --weighted_captions
            False,  # 174 --xformers
            False,  # 175 --zero3_init_flag
            False,  # 176 --zero3_save_16bit_model
            "",     # 177 --zero_stage
            False,  # 178 --zero_terminal_snr
        ]

    # ────────────────────────────────────────────────
    # Step 4: /start_training — 启动训练
    # ────────────────────────────────────────────────

    def _start_training(self, client, base_model: str,
                        lora_name: str, train_script: str,
                        train_config: str,
                        sample_prompts: str = "") -> Any:
        """启动 LoRA 训练

        API: /start_training
          参数 (5个):
            - base_model (Literal['flux-dev', 'flux-schnell', 'bdsqlsz/flux1-dev2pro-single'])
            - lora_name (str)
            - train_script (str) — /update 返回
            - train_config (str) — /update 返回
            - sample_prompts (str, 默认 "")

          返回: List[Any] — 训练日志
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

    # ────────────────────────────────────────────────
    # 工具方法
    # ────────────────────────────────────────────────

    def _find_api(self, client, keyword: str, fallback: str) -> str:
        """查找包含 keyword 的 API 端点"""
        try:
            info = client.view_api(return_format="dict")
            endpoints = info.get("named_endpoints", {})
            if fallback in endpoints:
                return fallback
            for name in endpoints:
                if keyword in name.lower():
                    return name
        except Exception as e:
            logger.debug(f"API 端点发现失败: {e}")
        return fallback

    def _resolve_resolution(self, resolution: str | int) -> int:
        """解析分辨率字符串为整数"""
        if isinstance(resolution, int):
            return resolution
        try:
            return int(str(resolution).split("x")[0])
        except (ValueError, AttributeError):
            return self._default_resolution

    # ────────────────────────────────────────────────
    # 主入口
    # ────────────────────────────────────────────────

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
            steps: 训练步数（用于计算 max_train_epochs）
            learning_rate: 学习率
            rank: LoRA rank (network_dim)
            resolution: 训练分辨率（如 "512x768"）
            output_name: 输出文件名（默认 {char_id}_lora）

        Returns:
            本地 .safetensors 路径
        """
        if not output_name:
            output_name = f"{char_id}_lora"
        if not trigger_word:
            trigger_word = f"ohwx {char_id}"

        res_val = self._resolve_resolution(resolution)
        lr_str = str(learning_rate) if isinstance(learning_rate, float) else learning_rate

        # 收集 + 验证图片
        img_paths = self._collect_images(images_dir)
        img_paths = self._validate_paths(img_paths)
        if not img_paths:
            raise FileNotFoundError(f"训练图片目录中无有效图片: {images_dir}")

        logger.info(f"开始训练 LoRA: {char_id}, 图片 {len(img_paths)} 张, "
                    f"steps={steps}, rank={rank}, resolution={res_val}")

        client = self._get_client()

        # Step 1: 自动打标
        logger.info("[1/4] 自动打标...")
        captions = self._load_captioning(client, img_paths, trigger_word)

        # Step 2: 创建数据集
        logger.info("[2/4] 创建数据集...")
        self._create_dataset(client, img_paths, captions, res_val)

        # Step 3: 生成训练配置
        logger.info("[3/4] 生成训练配置...")
        train_script, train_config = self._update_config(
            client, trigger_word, output_name,
            steps, lr_str, rank, res_val,
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
        img_paths = self._validate_paths(img_paths)
        if not img_paths:
            raise FileNotFoundError(f"风格图片目录中无有效图片: {images_dir}")

        logger.info(f"开始训练风格 LoRA: {genre}, 图片 {len(img_paths)} 张")

        client = self._get_client()

        captions = self._load_captioning(client, img_paths, trigger_word)
        self._create_dataset(client, img_paths, captions, self._default_resolution)
        train_script, train_config = self._update_config(
            client, trigger_word, output_name,
            steps, self._default_learning_rate, rank, self._default_resolution,
        )
        result = self._start_training(
            client, self._base_model, output_name,
            train_script, train_config,
        )

        return self._download_result(result, f"style_{genre}")

    # ────────────────────────────────────────────────
    # 结果下载
    # ────────────────────────────────────────────────

    def _download_result(self, result: Any, prefix: str) -> str:
        """下载训练结果到本地

        /start_training 返回 List[Any]（训练日志），实际 .safetensors 文件
        在 FluxGym 服务器的输出目录中。尝试多种方式获取。

        Returns:
            本地 .safetensors 路径
        """
        if not self._project_dir:
            raise RuntimeError("FluxGymTrainer: project_dir 为空，无法下载结果")

        output_dir = Path(self._project_dir) / "assets" / "loras"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{prefix}.safetensors"

        lora_name = f"{prefix}_lora" if not prefix.endswith("_lora") else prefix

        # 1. FluxGym 本地输出目录
        for base in [
            Path(f"/workspace/fluxgym/outputs/{lora_name}"),
            Path(f"/workspace/fluxgym/outputs/{prefix}"),
            Path.home() / "fluxgym" / "outputs" / lora_name,
        ]:
            try:
                if base and base.exists():
                    for f in base.glob("**/*.safetensors"):
                        shutil.copy2(str(f), str(output_path))
                        logger.info(f"  复制: {f}")
                        return str(output_path)
            except (TypeError, OSError):
                continue

        # 2. result 中的路径/URL
        candidates = []
        if isinstance(result, str) and result:
            candidates.append(result)
        elif isinstance(result, (list, tuple)):
            candidates.extend(item for item in result if isinstance(item, str) and item)

        for item in candidates:
            try:
                p = Path(item)
                if p.exists() and p.suffix == ".safetensors":
                    shutil.copy2(str(p), str(output_path))
                    return str(output_path)
            except (TypeError, OSError):
                pass
            if item.startswith("http") and ".safetensors" in item:
                try:
                    import httpx
                    resp = httpx.get(item, timeout=120)
                    resp.raise_for_status()
                    output_path.write_bytes(resp.content)
                    return str(output_path)
                except Exception:
                    pass

        logger.warning(
            f"  无法自动获取 LoRA 文件。训练已在 FluxGym 服务器上启动。\n"
            f"  请在训练完成后将 .safetensors 复制到: {output_path}\n"
            f"  FluxGym 输出目录: /workspace/fluxgym/outputs/{lora_name}/"
        )
        return str(output_path)

    # ────────────────────────────────────────────────
    # 状态查询
    # ────────────────────────────────────────────────

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

    def get_samples(self, lora_name: str) -> list[dict]:
        """获取训练样本预览 (/get_samples)"""
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
        self._client = None


# ── 注册 ──

registry.register(BackendMeta(
    name="fluxgym",
    service_type="training",
    factory=lambda cfg: FluxGymTrainer(cfg),
    description="FluxGym 远程 LoRA 训练（Gradio API）",
    priority=10,
    tags=["lora", "training", "flux", "gradio"],
))

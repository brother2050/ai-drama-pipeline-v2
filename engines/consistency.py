"""角色一致性 — 人脸嵌入比对 + IP-Adapter 参考图注入

支持三种模式（按优先级自动选择）：
1. insightface — 最佳精度，需要 insightface + onnxruntime
2. face_recognition — 次选，需要 dlib
3. 图片哈希回退 — 无需额外依赖，仅做基础相似度
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading

logger = logging.getLogger(__name__)

# 尝试加载人脸库
_face_engine: str | None = None

try:
    import insightface
    import numpy as np
    from PIL import Image

    _face_engine = "insightface"
    logger.info("人脸引擎: insightface")
except ImportError:
    pass

if _face_engine is None:
    try:
        import face_recognition
        import numpy as np

        _face_engine = "face_recognition"
        logger.info("人脸引擎: face_recognition")
    except ImportError:
        pass

if _face_engine is None:
    logger.info("人脸引擎: 图片哈希回退（安装 insightface 或 face_recognition 可获得更好精度）")


class CharacterConsistency:
    """角色一致性管理器"""

    def __init__(self):
        self._cache: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._engine = _face_engine
        self._insightface_app = None

    def _get_insightface_app(self):
        """懒加载 insightface app（线程安全双重检查锁定）"""
        if self._insightface_app is None and self._engine == "insightface":
            with self._lock:
                if self._insightface_app is None and self._engine == "insightface":
                    try:
                        self._insightface_app = insightface.app.FaceAnalysis(
                            name="buffalo_l", providers=["CPUExecutionProvider"]
                        )
                        self._insightface_app.prepare(ctx_id=0, det_size=(640, 640))
                    except Exception as e:
                        logger.warning(f"insightface 初始化失败: {e}")
                        self._engine = "hash"
        return self._insightface_app

    def prepare_embedding(self, char_id: str, ref_images: list[str], output_dir: str) -> str:
        """准备角色嵌入

        Returns:
            嵌入文件路径（JSON 格式）
        """
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, f"{char_id}_embedding.json")

        embeddings = []
        for img_path in ref_images:
            if not os.path.exists(img_path):
                logger.warning(f"参考图不存在: {img_path}")
                continue
            emb = self._extract_embedding(img_path)
            if emb is not None:
                embeddings.append({"image": img_path, "embedding": emb})

        data = {
            "character_id": char_id,
            "engine": self._engine or "none",
            "images": ref_images,
            "embeddings": embeddings,
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        return path

    def _extract_embedding(self, image_path: str) -> list[float] | None:
        """提取人脸嵌入向量"""
        try:
            if self._engine == "insightface":
                return self._extract_insightface(image_path)
            elif self._engine == "face_recognition":
                return self._extract_face_recognition(image_path)
            else:
                return self._extract_hash(image_path)
        except Exception as e:
            logger.warning(f"嵌入提取失败 [{image_path}]: {e}")
            return self._extract_hash(image_path)

    def _extract_insightface(self, image_path: str) -> list[float] | None:
        app = self._get_insightface_app()
        if app is None:
            return self._extract_hash(image_path)
        with Image.open(image_path) as pil_img:
            img = np.array(pil_img.convert("RGB"))
        faces = app.get(img)
        if not faces:
            logger.warning(f"未检测到人脸: {image_path}")
            return self._extract_hash(image_path)
        return faces[0].embedding.tolist()

    def _extract_face_recognition(self, image_path: str) -> list[float] | None:
        img = face_recognition.load_image_file(image_path)
        encodings = face_recognition.face_encodings(img)
        if not encodings:
            logger.warning(f"未检测到人脸: {image_path}")
            return self._extract_hash(image_path)
        return encodings[0].tolist()

    def _extract_hash(self, image_path: str) -> list[float] | None:
        """基于图片哈希的回退方案（精度低但无依赖）"""
        try:
            with open(image_path, "rb") as f:
                data = f.read()
            h = hashlib.sha256(data).hexdigest()
            # 转为伪浮点向量（仅用于缓存比对，非真实嵌入）
            return [int(h[i:i+2], 16) / 255.0 for i in range(0, 64, 2)]
        except Exception:
            return None

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
        """验证生成图与参考图的一致性分数

        Returns:
            0.0~1.0 的一致性分数
        """
        if not os.path.exists(generated):
            logger.warning(f"生成图不存在: {generated}")
            return 0.0

        gen_emb = self._extract_embedding(generated)
        if gen_emb is None:
            return 0.0

        scores = []
        for ref in references:
            if not os.path.exists(ref):
                continue
            ref_emb = self._extract_embedding(ref)
            if ref_emb is None:
                continue
            score = self._compute_similarity(gen_emb, ref_emb)
            scores.append(score)

        if not scores:
            return 0.0

        avg_score = sum(scores) / len(scores)
        logger.debug(f"一致性分数: {avg_score:.3f} (阈值: {threshold})")
        return round(avg_score, 4)

    def _compute_similarity(self, emb1: list[float], emb2: list[float]) -> float:
        """计算两个嵌入向量的余弦相似度"""
        try:
            import numpy as np
            a = np.array(emb1)
            b = np.array(emb2)
            if a.shape != b.shape:
                return 0.0
            dot = np.dot(a, b)
            norm = np.linalg.norm(a) * np.linalg.norm(b)
            if norm == 0:
                return 0.0
            return float(dot / norm)
        except ImportError:
            # 纯 Python 回退
            if len(emb1) != len(emb2):
                return 0.0
            dot = sum(x * y for x, y in zip(emb1, emb2))
            norm1 = sum(x * x for x in emb1) ** 0.5
            norm2 = sum(y * y for y in emb2) ** 0.5
            if norm1 == 0 or norm2 == 0:
                return 0.0
            return dot / (norm1 * norm2)

    def shutdown(self):
        with self._lock:
            self._cache.clear()
            self._insightface_app = None

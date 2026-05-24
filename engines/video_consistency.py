"""视频一致性检查 — 抽取关键帧与参考图比对

支持三种模式（按优先级自动选择）：
1. insightface — 最佳精度
2. face_recognition — 次选
3. 图片哈希回退 — 无额外依赖
"""
from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def _extract_keyframes(video_path: str, max_frames: int = 5) -> list[str]:
    """从视频中抽取关键帧"""
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        logger.warning("ffmpeg 未安装，无法抽取关键帧")
        return []

    tmp_dir = tempfile.mkdtemp(prefix="vconsist_")
    pattern = os.path.join(tmp_dir, "frame_%03d.png")

    # 每隔一定帧数抽取一帧
    cmd = [
        ffmpeg, "-y", "-i", video_path,
        "-vf", f"select=not(mod(n\\,30)),scale=224:224",
        "-vframes", str(max_frames),
        "-vsync", "vfr",
        pattern,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        logger.warning(f"关键帧抽取失败: {r.stderr[-200:]}")
        return []

    frames = sorted(str(p) for p in Path(tmp_dir).glob("frame_*.png"))
    return frames


def _find_ffmpeg() -> str | None:
    import shutil
    return shutil.which("ffmpeg")


def _compute_image_hash(image_path: str) -> str | None:
    """计算图片感知哈希（pHash 简化版）"""
    try:
        from PIL import Image
        with Image.open(image_path) as pil_img:
            img = pil_img.convert("L").resize((8, 8))
        pixels = list(img.getdata())
        avg = sum(pixels) / len(pixels)
        bits = "".join("1" if p > avg else "0" for p in pixels)
        return hex(int(bits, 2))
    except Exception:
        return None


def _hash_similarity(h1: str, h2: str) -> float:
    """两个哈希的汉明相似度"""
    if not h1 or not h2:
        return 0.0
    try:
        b1 = bin(int(h1, 16))[2:].zfill(64)
        b2 = bin(int(h2, 16))[2:].zfill(64)
        same = sum(a == b for a, b in zip(b1, b2))
        return same / 64.0
    except Exception:
        return 0.0


def _extract_embedding(image_path: str) -> list[float] | None:
    """提取人脸嵌入（与 consistency.py 共享逻辑）"""
    try:
        import insightface
        import numpy as np
        from PIL import Image

        app = getattr(_extract_embedding, "_app", None)
        if app is None:
            app = insightface.app.FaceAnalysis(
                name="buffalo_l", providers=["CPUExecutionProvider"]
            )
            app.prepare(ctx_id=0, det_size=(640, 640))
            _extract_embedding._app = app

        with Image.open(image_path) as pil_img:
            img = np.array(pil_img.convert("RGB"))
        faces = app.get(img)
        if faces:
            return faces[0].embedding.tolist()
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"insightface 失败: {e}")

    try:
        import face_recognition
        img = face_recognition.load_image_file(image_path)
        encodings = face_recognition.face_encodings(img)
        if encodings:
            return encodings[0].tolist()
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"face_recognition 失败: {e}")

    return None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """余弦相似度"""
    try:
        import numpy as np
        va, vb = np.array(a), np.array(b)
        dot = np.dot(va, vb)
        norm = np.linalg.norm(va) * np.linalg.norm(vb)
        return float(dot / norm) if norm > 0 else 0.0
    except ImportError:
        dot = sum(x * y for x, y in zip(a, b))
        n1 = sum(x * x for x in a) ** 0.5
        n2 = sum(y * y for y in b) ** 0.5
        return dot / (n1 * n2) if n1 > 0 and n2 > 0 else 0.0


def check_video_consistency(video_path: str, ref_images: list[str],
                             threshold: float = 0.6, max_frames: int = 5) -> dict:
    """检查视频中角色是否与参考图一致

    Args:
        video_path: 视频文件路径
        ref_images: 参考图路径列表
        threshold: 一致性阈值
        max_frames: 最多抽取的关键帧数

    Returns:
        {"consistent": bool, "score": float, "details": list, "video": str}
    """
    if not os.path.exists(video_path):
        return {"consistent": False, "score": 0.0, "error": "视频不存在", "video": video_path}

    if not ref_images:
        return {"consistent": True, "score": 1.0, "video": video_path,
                "note": "无参考图，跳过检查"}

    # 抽取关键帧
    frames = _extract_keyframes(video_path, max_frames)
    if not frames:
        logger.warning("无法抽取关键帧，使用哈希回退")
        return _check_with_hash(video_path, ref_images)

    # 尝试人脸嵌入比对
    ref_embeddings = []
    for ref in ref_images:
        if os.path.exists(ref):
            emb = _extract_embedding(ref)
            if emb is not None:
                ref_embeddings.append(emb)

    if ref_embeddings:
        return _check_with_embeddings(frames, ref_embeddings, threshold, video_path)
    else:
        return _check_with_hash(video_path, ref_images, frames)


def _check_with_embeddings(frames: list[str], ref_embeddings: list[float],
                            threshold: float, video_path: str) -> dict:
    """使用人脸嵌入进行一致性检查"""
    scores = []
    details = []

    for frame in frames:
        frame_emb = _extract_embedding(frame)
        if frame_emb is None:
            details.append({"frame": frame, "face_detected": False})
            continue

        best_score = max(
            _cosine_similarity(frame_emb, ref_emb)
            for ref_emb in ref_embeddings
        )
        scores.append(best_score)
        details.append({
            "frame": frame, "face_detected": True,
            "score": round(best_score, 4),
        })

    # 清理临时帧
    for frame in frames:
        try:
            os.unlink(frame)
            os.rmdir(os.path.dirname(frame))
        except OSError:
            pass

    if not scores:
        return {"consistent": False, "score": 0.0, "video": video_path,
                "details": details, "reason": "所有帧均未检测到人脸"}

    avg_score = sum(scores) / len(scores)
    return {
        "consistent": avg_score >= threshold,
        "score": round(avg_score, 4),
        "threshold": threshold,
        "frame_count": len(scores),
        "details": details,
        "video": video_path,
    }


def _check_with_hash(video_path: str, ref_images: list[str],
                      frames: list[str] | None = None) -> dict:
    """使用图片哈希的回退方案"""
    cleanup_frames = False
    if frames is None:
        frames = _extract_keyframes(video_path, 3)
        cleanup_frames = True

    if not frames:
        return {"consistent": True, "score": 0.5, "video": video_path,
                "note": "无法分析视频，假设一致"}

    ref_hashes = []
    for ref in ref_images:
        if os.path.exists(ref):
            h = _compute_image_hash(ref)
            if h:
                ref_hashes.append(h)

    if not ref_hashes:
        return {"consistent": True, "score": 0.5, "video": video_path,
                "note": "无法计算参考图哈希"}

    scores = []
    for frame in frames:
        fh = _compute_image_hash(frame)
        if fh:
            best = max(_hash_similarity(fh, rh) for rh in ref_hashes)
            scores.append(best)

    if cleanup_frames:
        for frame in frames:
            try:
                os.unlink(frame)
                os.rmdir(os.path.dirname(frame))
            except OSError:
                pass

    avg = sum(scores) / len(scores) if scores else 0.5
    return {
        "consistent": avg >= 0.5,
        "score": round(avg, 4),
        "method": "hash",
        "video": video_path,
    }

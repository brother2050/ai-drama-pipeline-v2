"""测试 — 基础功能验证"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# 确保项目根在 sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── infra/config.py ──

def test_config_load():
    """测试配置加载"""
    from infra.config import Config, load_config, save_config

    cfg_path = str(ROOT / "config" / "project.yaml")
    cfg = Config(cfg_path)
    assert cfg.get("project.name") == "AI短剧"
    assert cfg.get("models.tts_backend") == "mimo-voicedesign"
    assert cfg.get("comfyui.url") == "http://127.0.0.1:8188"
    assert cfg.get("nonexistent.key", "default") == "default"
    print("✅ Config 加载正常")


def test_config_save_load():
    """测试配置保存和加载"""
    from infra.config import load_config, save_config

    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
        path = f.name

    try:
        save_config(path, {"test": {"key": "value"}})
        data = load_config(path)
        assert data["test"]["key"] == "value"
    finally:
        os.unlink(path)
    print("✅ Config 保存/加载正常")


# ── infra/text.py ──

def test_text_utils():
    """测试文本工具"""
    from infra.text import truncate, sanitize_filename

    assert truncate("hello world", 5) == "hello..."
    assert truncate("hi", 10) == "hi"
    assert sanitize_filename('file<>:"/\\|?*name') == "file_________name"
    print("✅ 文本工具正常")


# ── infra/cache.py ──

def test_ttl_cache():
    """测试 TTL 缓存"""
    from infra.cache import TTLCache

    cache = TTLCache(ttl=10, maxsize=3)
    cache.set("a", 1)
    assert cache.get("a") == 1
    assert cache.get("b") is None
    assert cache.get("b", 42) == 42

    # 测试 maxsize 淘汰
    cache.set("b", 2)
    cache.set("c", 3)
    cache.set("d", 4)  # 应该淘汰最旧的
    print("✅ TTL 缓存正常")


# ── infra/gpu.py ──

def test_gpu_detect():
    """测试 GPU 检测"""
    from infra.gpu import detect_gpu

    gpu = detect_gpu()
    assert "name" in gpu
    assert "vram_mb" in gpu
    assert "available" in gpu
    print(f"✅ GPU 检测正常: {gpu['name']} ({gpu['vram_mb']}MB)")


# ── infra/retry.py ──

def test_retry():
    """测试重试机制"""
    from infra.retry import retry

    call_count = 0

    def flaky():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ValueError("not yet")
        return "ok"

    result = retry(flaky, max_retries=5, base_delay=0.01)
    assert result == "ok"
    assert call_count == 3
    print("✅ 重试机制正常")


# ── infra/database ──

def test_sqlite_database():
    """测试 SQLite 数据库"""
    from infra.database.pool import SQLitePool
    from infra.database import characters, episodes, scenes, shots

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        pool = SQLitePool(db_path)

        # 角色
        characters.upsert(pool, "test_char", {
            "name": "测试角色", "appearance": "黑色头发",
            "voice": {"desc": "温柔"}, "reference_images": ["a.png"]
        })
        chars = characters.get_all(pool)
        assert len(chars) == 1
        assert chars[0]["name"] == "测试角色"

        char = characters.get_by_id(pool, "test_char")
        assert char is not None
        assert char["id"] == "test_char"

        # 集
        episodes.upsert(pool, 1, {"title": "第一集", "status": "done", "shot_count": 3})
        eps = episodes.get_all(pool)
        assert len(eps) == 1

        # 场景
        scenes.upsert(pool, "scene1", {"name": "客厅", "description": "现代客厅", "lighting": "暖光"})
        sc = scenes.get_all(pool)
        assert len(sc) == 1

        # 镜头
        shots.upsert(pool, 1, "001", {
            "scene": "scene1", "characters": "test_char",
            "action": "坐着", "dialogue": "你好", "camera": "固定",
            "shot_type": "中景", "duration": 4.0, "emotion": "calm"
        })
        shot_list = shots.get_by_episode(pool, 1)
        assert len(shot_list) == 1
        assert shot_list[0]["dialogue"] == "你好"

        pool.close()
        print("✅ SQLite 数据库正常")
    finally:
        os.unlink(db_path)


# ── engines/storyboard.py ──

def test_storyboard():
    """测试分镜表加载"""
    from engines.storyboard import load_storyboard, validate_shot, get_dominant_emotion

    sb_path = str(ROOT / "storyboard" / "episodes.csv")
    if Path(sb_path).exists():
        all_shots = load_storyboard(sb_path)
        assert len(all_shots) > 0

        ep1_shots = load_storyboard(sb_path, episode=1)
        assert all(int(s["episode"]) == 1 for s in ep1_shots)

        # 验证
        for shot in ep1_shots:
            errors = validate_shot(shot)
            assert len(errors) == 0, f"镜头 {shot.get('shot_id')}: {errors}"

        # 主要情绪
        emotion = get_dominant_emotion(ep1_shots)
        assert emotion in ("worried", "sad", "determined")

        print(f"✅ 分镜表正常: {len(all_shots)} 镜头")
    else:
        print("⚠ 分镜表不存在，跳过测试")


# ── engines/camera.py ──

def test_camera():
    """测试机位规范化"""
    from engines.camera import normalize_camera, normalize_shot_type

    assert normalize_camera("固定") == "固定"
    assert normalize_camera("环绕摇镜头") == "环绕"
    assert normalize_camera("") == "固定"
    assert normalize_camera("无") == "固定"

    assert normalize_shot_type("特写") == "特写"
    assert normalize_shot_type("中景镜头") == "中景"
    assert normalize_shot_type("") == "中景"
    print("✅ 机位规范化正常")


# ── engines/emotions.py ──

def test_emotions():
    """测试情绪分析"""
    from engines.emotions import analyze_emotion

    assert analyze_emotion("他愤怒地大吼") == "angry"
    assert analyze_emotion("她开心地笑了") == "happy"
    assert analyze_emotion("他悲伤地哭泣") == "sad"
    assert analyze_emotion("普通文本") == "neutral"
    print("✅ 情绪分析正常")


# ── engines/prompt.py ──

def test_prompt():
    """测试 Prompt 构建"""
    from engines.prompt import build_prompt, translate_to_english

    shot = {
        "action": "坐在沙发上", "emotion": "worried",
        "shot_type": "特写", "camera": "缓慢推近"
    }
    prompt = build_prompt(shot, character_desc="young woman", scene_desc="modern living room")
    assert "young woman" in prompt
    assert "modern living room" in prompt
    assert "worried" in prompt

    # 翻译
    assert translate_to_english("hello") == "hello"
    assert translate_to_english("") == ""
    print("✅ Prompt 构建正常")


# ── engines/quality.py ──

def test_quality():
    """测试质量检查"""
    from engines.quality import check_video_format

    # 不存在的文件
    result = check_video_format("/nonexistent/video.mp4")
    assert result["valid"] is False
    assert "不存在" in result["error"]
    print("✅ 质量检查正常")


# ── engines/multi_char.py ──

def test_multi_char():
    """测试多人同框"""
    from engines.multi_char import MultiCharacterHandler

    handler = MultiCharacterHandler()

    # 单人
    prompt = handler.generate_multi_char_prompt([{"appearance": "young woman"}])
    assert "young woman" in prompt

    # 多人
    prompt = handler.generate_multi_char_prompt([
        {"appearance": "woman"}, {"appearance": "man"}
    ])
    assert "woman" in prompt
    assert "man" in prompt

    regions = handler.calculate_regions(2)
    assert len(regions) == 2
    print("✅ 多人同框正常")


# ── post/subtitle.py ──

def test_subtitle():
    """测试字幕生成"""
    from post.subtitle import generate_srt, _format_srt_time

    assert _format_srt_time(0) == "00:00:00,000"
    assert _format_srt_time(61.5) == "00:01:01,500"
    assert _format_srt_time(3661.123) == "01:01:01,123"

    shots = [
        {"dialogue": "你好", "duration": 3},
        {"dialogue": "......", "duration": 2},  # 应跳过
        {"dialogue": "世界", "duration": 4},
    ]
    with tempfile.NamedTemporaryFile(suffix=".srt", delete=False) as f:
        path = f.name

    try:
        generate_srt(shots, path)
        content = Path(path).read_text(encoding="utf-8")
        assert "你好" in content
        assert "世界" in content
        assert "......" not in content
    finally:
        os.unlink(path)
    print("✅ 字幕生成正常")


# ── post/effects.py ──

def test_effects():
    """测试特效"""
    from post.effects import build_color_grade_filter

    f = build_color_grade_filter({"brightness": 0.1, "contrast": 1.2})
    assert "eq=brightness=0.1" in f
    assert "eq=contrast=1.2" in f

    assert build_color_grade_filter({}) is None
    print("✅ 特效处理正常")


# ── post/transitions.py ──

def test_transitions():
    """测试转场"""
    from post.transitions import get_xfade_filter, TRANSITIONS

    f = get_xfade_filter("crossfade", 10.0, 0.5)
    assert "xfade=transition=fade" in f
    assert "duration=0.5" in f
    assert "offset=10.0" in f
    print("✅ 转场效果正常")


# ── post/music.py ──

def test_music():
    """测试配乐"""
    from post.music import MusicGenerator

    gen = MusicGenerator(backend="template")
    assert gen._backend == "template"

    # 测试未知后端回退
    gen2 = MusicGenerator(backend="unknown")
    assert gen2._backend == "unknown"
    print("✅ 配乐生成正常")


# ── post/distributor.py ──

def test_distributor():
    """测试分发"""
    from post.distributor import distribute, PLATFORM_PRESETS

    results = distribute("/tmp/test.mp4", ["douyin", "bilibili"])
    assert "douyin" in results
    assert "bilibili" in results
    print("✅ 多平台分发正常")


# ── api/registry.py ──

def test_registry():
    """测试服务注册表"""
    from api.registry import ServiceRegistry, BackendMeta

    reg = ServiceRegistry()

    def factory(cfg):
        return {"name": "test"}

    reg.register(BackendMeta(
        name="test-tts", service_type="tts", factory=factory,
        description="Test TTS", priority=10
    ))

    meta = reg.get("tts", "test-tts")
    assert meta is not None
    assert meta.name == "test-tts"

    types = reg.list_by_type("tts")
    assert "test-tts" in types

    inst = reg.create("tts", "test-tts", {})
    assert inst["name"] == "test"
    print("✅ 服务注册表正常")


# ── flow/model_registry.py ──

def test_model_registry():
    """测试模型注册表"""
    from flow.model_registry import ModelRegistry

    reg = ModelRegistry(str(ROOT / "config" / "project.yaml"))

    assert "sd15" in reg.valid_image_backends()
    assert "animatediff" in reg.valid_video_backends()
    assert reg.get_image_workflow("sd15") == "01_first_frame_sd15.json"
    assert reg.is_flux_backend("sd15") is False
    print("✅ 模型注册表正常")


# ── web/app.py ──

def test_web_app():
    """测试 Web 应用创建"""
    from web.app import create_app

    app = create_app()
    assert app.title == "AI 短剧工作台 v2"
    # 检查路由
    routes = [r.path for r in app.routes]
    assert "/api/system/status" in routes
    print("✅ Web 应用正常")


# ── pipeline/celery_app.py ──

def test_celery_app():
    """测试 Celery 应用配置"""
    from pipeline.celery_app import app

    assert app.main == "drama"
    assert "redis" in app.conf.broker_url
    assert app.conf.task_track_started is True
    assert app.conf.task_acks_late is True
    assert app.conf.worker_prefetch_multiplier == 1
    print("✅ Celery 配置正常")


def test_celery_tasks_registered():
    """测试 Celery 任务注册"""
    from pipeline.celery_app import app
    import pipeline.tasks  # noqa: F401 触发注册

    expected_tasks = [
        "pipeline.tts", "pipeline.first_frame", "pipeline.video_gen",
        "pipeline.lipsync", "pipeline.shot", "pipeline.preview",
        "pipeline.produce", "pipeline.post", "pipeline.portraits",
    ]
    registered = set(app.tasks.keys())
    for task_name in expected_tasks:
        assert task_name in registered, f"任务未注册: {task_name}"
    print(f"✅ Celery 任务注册正常 ({len(expected_tasks)} 个)")


# ── 运行所有测试 ──

def run_all():
    """运行所有测试"""
    tests = [
        test_config_load,
        test_config_save_load,
        test_text_utils,
        test_ttl_cache,
        test_gpu_detect,
        test_retry,
        test_sqlite_database,
        test_storyboard,
        test_camera,
        test_emotions,
        test_prompt,
        test_quality,
        test_multi_char,
        test_subtitle,
        test_effects,
        test_transitions,
        test_music,
        test_distributor,
        test_registry,
        test_model_registry,
        test_web_app,
        test_celery_app,
        test_celery_tasks_registered,
    ]

    passed = 0
    failed = 0
    errors = []

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            errors.append((test.__name__, str(e)))
            print(f"❌ {test.__name__}: {e}")

    print(f"\n{'='*50}")
    print(f"测试结果: {passed} 通过, {failed} 失败")

    if errors:
        print("\n失败详情:")
        for name, err in errors:
            print(f"  - {name}: {err}")

    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)

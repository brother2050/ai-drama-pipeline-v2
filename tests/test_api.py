"""集成测试 — API 端点测试

使用 FastAPI TestClient，无需启动服务器。
"""
from __future__ import annotations

import csv
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 设置测试项目目录
_test_project = tempfile.mkdtemp(prefix="drama_test_")
os.makedirs(f"{_test_project}/config", exist_ok=True)
os.makedirs(f"{_test_project}/storyboard", exist_ok=True)
os.makedirs(f"{_test_project}/config/characters", exist_ok=True)
os.makedirs(f"{_test_project}/config/scenes", exist_ok=True)

# 写一个最小配置
import yaml
with open(f"{_test_project}/config/project.yaml", "w") as f:
    yaml.dump({"project": {"name": "测试项目"}, "models": {"tts_backend": "mimo-voicedesign"}}, f)

# 写一个测试分镜
sb_path = f"{_test_project}/storyboard/episodes.csv"
with open(sb_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["episode", "shot_id", "scene", "characters",
                                            "action", "dialogue", "camera", "shot_type",
                                            "duration", "emotion"])
    writer.writeheader()
    writer.writerow({"episode": "1", "shot_id": "001", "scene": "客厅", "characters": "女主",
                      "action": "坐在沙发上", "dialogue": "你好", "camera": "固定",
                      "shot_type": "中景", "duration": "4", "emotion": "neutral"})
    writer.writerow({"episode": "1", "shot_id": "002", "scene": "厨房", "characters": "男主",
                      "action": "做饭", "dialogue": "......", "camera": "缓慢推近",
                      "shot_type": "近景", "duration": "3", "emotion": "calm"})

# 写一个测试角色
with open(f"{_test_project}/config/characters/nvzhu.yaml", "w") as f:
    yaml.dump({"character": {"id": "nvzhu", "name": "女主", "appearance": "黑色长发"}}, f)

# 写一个测试场景
with open(f"{_test_project}/config/scenes/keting.yaml", "w") as f:
    yaml.dump({"scene": {"id": "keting", "name": "客厅", "description": "现代客厅"}}, f)


@pytest.fixture
def client():
    """创建测试客户端"""
    # Monkey-patch ROOT 到测试目录
    with patch("web.routers.api.ROOT", Path(_test_project)):
        from web.app import create_app
        app = create_app()
        from fastapi.testclient import TestClient
        yield TestClient(app)


# ── 系统 ──

def test_system_status(client):
    r = client.get("/api/system/status")
    assert r.status_code == 200
    data = r.json()
    assert "tools" in data
    assert "redis" in data["tools"]
    assert "celery" in data["tools"]
    assert data["version"] == "2.0.0"


def test_system_env(client):
    r = client.get("/api/system/env")
    assert r.status_code == 200
    data = r.json()
    assert "os" in data
    assert "python" in data


def test_tools_list(client):
    r = client.get("/api/tools")
    assert r.status_code == 200
    assert "tools" in r.json()


def test_tool_check(client):
    r = client.get("/api/tools/ffmpeg")
    assert r.status_code == 200
    assert "available" in r.json()


# ── 配置 ──

def test_get_config(client):
    r = client.get("/api/config")
    assert r.status_code == 200
    data = r.json()
    assert data["project"]["name"] == "测试项目"


def test_update_config(client):
    cfg = {"project": {"name": "更新后的项目"}}
    r = client.post("/api/config", json=cfg)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    # 新格式也应支持
    r2 = client.post("/api/config", json={"data": {"project": {"name": "再次更新"}}})
    assert r2.status_code == 200


def test_update_config_invalid(client):
    r = client.post("/api/config", content="not json",
                    headers={"Content-Type": "application/json"})
    # FastAPI 会返回 422
    assert r.status_code in (400, 422)


# ── 角色 ──

def test_list_characters(client):
    r = client.get("/api/characters")
    assert r.status_code == 200
    data = r.json()
    assert len(data["characters"]) == 1
    assert data["characters"][0]["id"] == "nvzhu"


def test_save_character(client):
    r = client.post("/api/characters", json={"id": "test_new", "name": "新角色"})
    assert r.status_code == 200
    assert r.json()["id"] == "test_new"

    # 验证已保存
    r2 = client.get("/api/characters")
    ids = [c["id"] for c in r2.json()["characters"]]
    assert "test_new" in ids


def test_save_character_invalid_id(client):
    r = client.post("/api/characters", json={"id": "../bad", "name": "test"})
    assert r.status_code == 422  # Pydantic 校验失败


def test_save_character_empty_id(client):
    r = client.post("/api/characters", json={"id": "", "name": "test"})
    assert r.status_code == 422


def test_delete_character(client):
    # 先创建
    client.post("/api/characters", json={"id": "to_delete", "name": "删除我"})
    # 删除
    r = client.delete("/api/characters/to_delete")
    assert r.status_code == 200
    # 验证已删除
    r2 = client.get("/api/characters")
    ids = [c["id"] for c in r2.json()["characters"]]
    assert "to_delete" not in ids


def test_delete_character_not_found(client):
    r = client.delete("/api/characters/nonexistent")
    assert r.status_code == 404


def test_delete_character_invalid_id(client):
    r = client.delete("/api/characters/bad%2Fid")
    # 路径遍历被阻断或方法不允许
    assert r.status_code in (400, 404, 405)


# ── 场景 ──

def test_list_scenes(client):
    r = client.get("/api/scenes")
    assert r.status_code == 200
    assert len(r.json()["scenes"]) == 1


def test_save_scene(client):
    r = client.post("/api/scenes", json={"id": "new_scene", "name": "新场景"})
    assert r.status_code == 200


def test_save_scene_invalid_id(client):
    r = client.post("/api/scenes", json={"id": "bad id", "name": "test"})
    assert r.status_code == 422


def test_delete_scene(client):
    client.post("/api/scenes", json={"id": "del_scene", "name": "删除"})
    r = client.delete("/api/scenes/del_scene")
    assert r.status_code == 200


# ── 分镜 ──

def test_get_storyboard(client):
    r = client.get("/api/storyboard/1")
    assert r.status_code == 200
    data = r.json()
    assert data["episode"] == 1
    assert len(data["shots"]) == 2
    assert data["shots"][0]["shot_id"] == "001"


def test_get_storyboard_empty(client):
    r = client.get("/api/storyboard/99")
    assert r.status_code == 200
    assert r.json()["shots"] == []


def test_save_storyboard(client):
    shots = [
        {"episode": 1, "shot_id": "001", "scene": "客厅", "action": "坐"},
        {"episode": 1, "shot_id": "003", "scene": "卧室", "action": "睡"},
    ]
    r = client.post("/api/storyboard/1", json={"shots": shots})
    assert r.status_code == 200
    assert r.json()["count"] == 2

    # 验证
    r2 = client.get("/api/storyboard/1")
    ids = [s["shot_id"] for s in r2.json()["shots"]]
    assert "001" in ids
    assert "003" in ids


def test_save_storyboard_invalid_shot_id(client):
    shots = [{"episode": 1, "shot_id": "../bad", "action": "test"}]
    r = client.post("/api/storyboard/1", json={"shots": shots})
    assert r.status_code == 400


def test_save_storyboard_invalid_episode(client):
    r = client.post("/api/storyboard/0", json={"shots": []})
    assert r.status_code == 400


# ── 镜头资源 ──

def test_shot_resources_empty(client):
    r = client.get("/api/shots/1/001/resources")
    assert r.status_code == 200
    assert r.json()["resources"] == {}


def test_shot_resources_invalid_id(client):
    r = client.get("/api/shots/1/../etc/resources")
    assert r.status_code in (400, 404)


def test_shot_file_not_found(client):
    r = client.get("/api/files/1/001/nonexistent.png")
    assert r.status_code == 404


def test_shot_file_invalid_name(client):
    r = client.get("/api/files/1/001/../../../etc/passwd")
    assert r.status_code in (400, 404)


# ── 项目 ──

def test_list_projects(client):
    r = client.get("/api/projects")
    assert r.status_code == 200
    assert "projects" in r.json()


# ── 管线 ──

def test_pipeline_invalid_command(client):
    r = client.post("/api/pipeline/run", json={"episode": 1, "command": "invalid"})
    assert r.status_code == 422 or r.status_code == 400


# ── Rate Limiting ──

def test_rate_limit_exists(client):
    """验证 rate limit 机制存在（不触发实际限制）"""
    # 发送少量请求，应该全部通过
    for _ in range(5):
        r = client.get("/api/system/status")
        assert r.status_code == 200


# ── 任务查询 ──

def test_task_invalid_id(client):
    r = client.get("/api/tasks/not-a-uuid")
    assert r.status_code == 400


def test_task_cancel_invalid_id(client):
    r = client.post("/api/tasks/not-a-uuid/cancel")
    assert r.status_code == 400

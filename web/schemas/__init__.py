"""Pydantic 数据模型 — API 请求/响应校验"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator
import re

__all__ = [
    "StepRequest", "TTSRequest", "PostRequest", "MusicRequest",
    "SubtitleRequest", "PipelineRequest", "CharacterData", "SceneData",
    "ProjectCreate", "ProjectSwitch", "ConfigUpdate",
    "StoryboardGenRequest", "CharacterGenRequest", "SceneGenRequest", "ChatEditRequest",
    "SekoProposalRequest", "SekoProposalStatusRequest", "SekoProposalModifyRequest",
    "SekoImportRequest",
]


# ── 镜头步骤 ──

class StepRequest(BaseModel):
    episode: int = Field(..., ge=1, description="集数")
    shot_id: str = Field(..., min_length=1, max_length=20, description="镜头 ID")

    @field_validator("shot_id")
    @classmethod
    def validate_shot_id(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError("镜头 ID 只允许字母、数字、下划线、连字符")
        return v


# ── TTS ──

class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000, description="合成文本")
    voice_config: dict | None = None
    emotion: str = Field("neutral", pattern=r"^[a-z_]+$")
    language: str = Field("zh", pattern=r"^[a-z]{2}$")


# ── 后期 ──

class PostRequest(BaseModel):
    episode: int = Field(..., ge=1)
    vertical: bool = False


# ── 配乐 ──

class MusicRequest(BaseModel):
    duration: float = Field(..., gt=0, le=600, description="时长（秒）")
    mood: str = Field("neutral", max_length=50)


# ── 字幕 ──

class SubtitleRequest(BaseModel):
    episode: int = Field(..., ge=1)


# ── 管线 ──

class PipelineRequest(BaseModel):
    episode: int = Field(..., ge=1)
    command: str = Field("produce", pattern=r"^(preview|produce|post)$")
    level: str = Field("draft", pattern=r"^(draft|standard|high)$")
    vertical: bool = False


# ── 角色 ──

class CharacterData(BaseModel):
    id: str = Field(..., min_length=1, max_length=50)
    name: str = Field("", max_length=100)
    gender: str = Field("", max_length=10)
    personality: str = Field("", max_length=500)
    appearance: str = Field("", max_length=2000)
    voice: dict | None = None
    outfits: dict | None = None
    reference_images: list[str] | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_\-\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+$", v):
            raise ValueError("角色 ID 只允许字母、数字、中文、下划线、连字符")
        return v


# ── 场景 ──

class SceneData(BaseModel):
    id: str = Field(..., min_length=1, max_length=50)
    name: str = Field("", max_length=100)
    description: str = Field("", max_length=2000)
    lighting: str = Field("", max_length=200)

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_\-\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+$", v):
            raise ValueError("场景 ID 只允许字母、数字、中文、下划线、连字符")
        return v


# ── 项目 ──

class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_\-\u4e00-\u9fff]+$", v):
            raise ValueError("项目名只允许字母、数字、中文、下划线、连字符")
        return v


class ProjectSwitch(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if ".." in v or "/" in v or "\\" in v:
            raise ValueError("项目名包含非法字符")
        return v


# ── 配置 ──

class ConfigUpdate(BaseModel):
    """配置更新（接受任意 dict，由路由层做额外校验）

    兼容两种格式:
    - 新格式: {"data": {...}}
    - 旧格式: {"project": {...}} (直接发送 config dict)
    """
    model_config = {"extra": "allow"}

    data: dict | None = None

    def get_config_data(self) -> dict:
        """提取配置数据，兼容新旧两种格式"""
        if self.data is not None:
            return self.data
        # 旧格式: 整个 body 就是配置 dict
        return self.model_extra or {}


# ── LLM 生成 ──

class StoryboardGenRequest(BaseModel):
    episode: int = Field(1, ge=1, description="集数")
    outline: str = Field(..., min_length=10, max_length=10000, description="剧情大纲")
    duration: int = Field(90, ge=10, le=600, description="目标时长（秒）")
    append: bool = Field(False, description="追加到现有分镜表")


class CharacterGenRequest(BaseModel):
    descriptions: list[str] = Field(..., min_length=1, max_length=10, description="角色描述列表")

    @field_validator("descriptions")
    @classmethod
    def validate_descs(cls, v: list[str]) -> list[str]:
        return [d.strip() for d in v if d.strip()]


class SceneGenRequest(BaseModel):
    descriptions: list[str] = Field(..., min_length=1, max_length=10, description="场景描述列表")

    @field_validator("descriptions")
    @classmethod
    def validate_descs(cls, v: list[str]) -> list[str]:
        return [d.strip() for d in v if d.strip()]


class ChatEditRequest(BaseModel):
    episode: int = Field(1, ge=1, description="集数")
    message: str = Field(..., min_length=1, description="编辑指令")
    shots: list = Field(default_factory=list, description="当前分镜表")


# ── Seko 影视策划案 ──

class SekoProposalRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=10000, description="策划案描述/故事梗概")
    api_key: str = Field("", description="Seko API Key（可选，默认从环境变量读取）")


class SekoProposalStatusRequest(BaseModel):
    task_id: str = Field(..., min_length=1, description="策划案任务 ID")
    api_key: str = Field("", description="Seko API Key（可选）")
    wait: bool = Field(False, description="是否轮询等待完成")
    interval: int = Field(10, ge=5, le=120, description="轮询间隔（秒）")
    download_dir: str = Field("", description="图片下载目录（留空则不下载）")


class SekoProposalModifyRequest(BaseModel):
    task_id: str = Field(..., min_length=1, description="原策划案任务 ID")
    prompt: str = Field(..., min_length=1, max_length=10000, description="修改指令")
    api_key: str = Field("", description="Seko API Key（可选）")


class SekoImportRequest(BaseModel):
    """Seko 策划案导入请求"""
    proposal_data: dict = Field(..., description="Seko 策划案完整 JSON（含 steps + elements）")
    episode: int = Field(1, ge=1, description="导入到第几集")
    import_characters: bool = Field(True, description="是否导入角色")
    import_scenes: bool = Field(True, description="是否导入场景")
    import_storyboard: bool = Field(True, description="是否导入分镜")
    download_images: bool = Field(True, description="是否下载角色/场景图片")
    project_name: str = Field("", max_length=100, description="创建新项目并导入（留空则导入当前项目）")

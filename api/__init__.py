"""API 后端层 — 触发所有后端自注册"""
from api.backends.tts import mimo_voicedesign, mimo_voiceclone, gpt_sovits
from api.backends.lipsync import musetalk
from api.backends.image import comfyui
from api.backends.llm import ollama
from api.backends.music import template

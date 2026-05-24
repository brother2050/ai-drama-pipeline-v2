"""API 后端层 — 触发所有后端自注册"""
from api.backends.tts import mimo_voicedesign, mimo_voiceclone, gpt_sovits, cosyvoice, fish_speech
from api.backends.lipsync import musetalk, wav2lip
from api.backends.image import comfyui
from api.backends.video import animatediff
from api.backends.llm import ollama
from api.backends.music import template

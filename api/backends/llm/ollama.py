"""Ollama / OpenAI 兼容 LLM — HTTP API"""
from __future__ import annotations
import logging
import httpx
from api.registry import BackendMeta, registry

logger = logging.getLogger(__name__)

class OllamaLLM:
    def __init__(self, config: dict):
        self._url = config.get("base_url", "http://localhost:11434")
        self._model = config.get("model", "qwen3:8b")
        self._timeout = config.get("timeouts", {}).get("llm", 300)

    @property
    def name(self): return "ollama"

    def chat(self, prompt: str, system: str = "", **kwargs) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        with httpx.Client(timeout=self._timeout) as c:
            r = c.post(f"{self._url}/api/chat", json={
                "model": self._model, "messages": messages, "stream": False,
                "options": {"num_predict": kwargs.get("max_tokens", 2048)},
            })
            r.raise_for_status()
            return r.json()["message"]["content"]

    def health_check(self) -> tuple[bool, str]:
        try:
            with httpx.Client(timeout=5) as c:
                r = c.get(f"{self._url}/api/tags")
                return True, f"Ollama reachable (HTTP {r.status_code})"
        except Exception as e:
            return False, f"Ollama unreachable: {e}"

    def shutdown(self): pass

def _f(config): return OllamaLLM(config)
registry.register(BackendMeta(name="ollama", service_type="llm", factory=_f,
    description="Ollama LLM", priority=10, tags=["api"]))


class OpenAICompatLLM:
    def __init__(self, config: dict):
        self._url = config.get("base_url", "http://localhost:8080").rstrip("/")
        self._model = config.get("model", "qwen2.5-7b")
        self._api_key = config.get("api_key", "")
        self._timeout = config.get("timeouts", {}).get("llm", 300)

    @property
    def name(self): return "openai"

    def chat(self, prompt: str, system: str = "", **kwargs) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        with httpx.Client(timeout=self._timeout) as c:
            r = c.post(f"{self._url}/v1/chat/completions", json={
                "model": self._model, "messages": messages,
                "max_tokens": kwargs.get("max_tokens", 2048),
            }, headers=headers)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

    def health_check(self) -> tuple[bool, str]:
        try:
            with httpx.Client(timeout=5) as c:
                r = c.get(f"{self._url}/v1/models")
                return True, f"OpenAI-compat reachable (HTTP {r.status_code})"
        except Exception as e:
            return False, f"OpenAI-compat unreachable: {e}"

    def shutdown(self): pass

def _f2(config): return OpenAICompatLLM(config)
registry.register(BackendMeta(name="openai", service_type="llm", factory=_f2,
    description="OpenAI 兼容 API", priority=50, tags=["api"]))

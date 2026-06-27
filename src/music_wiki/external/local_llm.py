from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Callable, Protocol


class LocalLLMClient(Protocol):
    model: str

    def complete(self, system: str, user: str, *,
                 json_schema: dict | None = None) -> str: ...


class OpenAICompatibleLLMClient:
    def __init__(self, base_url: str, model: str, *,
                 fetch: Callable[[str, dict], dict] | None = None,
                 sleep: Callable[[float], None] | None = None,
                 cache_dir: str | None = None,
                 temperature: float = 0.3, min_interval: float = 0.0,
                 timeout: int = 120):
        self.model = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._fetch = fetch or self._default_fetch
        self._sleep = sleep if sleep is not None else time.sleep
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self._temperature = temperature
        self._min_interval = min_interval
        self._timeout = timeout
        self._last = 0.0

    def _default_fetch(self, url: str, payload: dict) -> dict:
        import requests

        resp = requests.post(url, json=payload, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    def _cache_path(self, key_src: str) -> Path | None:
        if not self._cache_dir:
            return None
        key = hashlib.sha1(key_src.encode("utf-8")).hexdigest()
        return self._cache_dir / f"llm-{key}.json"

    def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last
        if elapsed < self._min_interval:
            self._sleep(self._min_interval - elapsed)
        self._last = time.monotonic()

    def complete(self, system: str, user: str, *,
                 json_schema: dict | None = None) -> str:
        key_src = f"{self.model}|{self._temperature}|{system}|{user}|{json_schema}"
        cache_file = self._cache_path(key_src)
        if cache_file and cache_file.exists():
            return cache_file.read_text(encoding="utf-8")

        payload: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self._temperature,
        }
        if json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "result", "schema": json_schema},
            }

        self._throttle()
        data = self._fetch(self._url, payload)   # exceptions propagate, not cached
        content = data["choices"][0]["message"]["content"]
        if cache_file:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(content, encoding="utf-8")
        return content

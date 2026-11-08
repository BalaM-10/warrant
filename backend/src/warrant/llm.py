"""One LLM behind one function. Temperature 0. Needs ANTHROPIC_API_KEY."""
from __future__ import annotations

import json
import os
import sys
import time

import httpx

from .classify import KEYWORDS


class AnthropicLLM:
    def __init__(self, model: str | None = None, api_key: str | None = None, transport=None):
        self.model = model or os.environ.get("WARRANT_MODEL", "claude-haiku-5-5")
        self.api_key = api_key or os.environ["ANTHROPIC_API_KEY"]
        self.client = httpx.Client(transport=transport, timeout=60)

    def __call__(self, system: str, user: str) -> str:
        r = self.client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
            json={"model": self.model, "max_tokens": 600, "temperature": 0,
                  "system": system, "messages": [{"role": "user", "content": user}]},
        )
        r.raise_for_status()
        return r.json()["content"][0]["text"]


class OpenAICompatLLM:
    """Any OpenAI-style /chat/completions endpoint. Default is NVIDIA's free hosted API
    (key in NVIDIA_API_KEY). Temperature 0, thinking off, retries on rate limits. Counts failures
    so the scorecard can report them instead of hiding them as hand-offs."""

    def __init__(self, model: str, base_url: str = "https://integrate.api.nvidia.com/v1",
                 key_env: str = "NVIDIA_API_KEY", transport=None, sleep=time.sleep, think_off: bool = True,
                 retries: int = 5):
        self.model, self.base_url, self.sleep, self.think_off = model, base_url.rstrip("/"), sleep, think_off
        self.retries = retries
        self.api_key = os.environ[key_env]
        self.client = httpx.Client(transport=transport, timeout=60)
        self.calls = self.errors = 0
        self.progress = transport is None  # live progress on stderr for real runs

    def __call__(self, system: str, user: str) -> str:
        body = {"model": self.model, "temperature": 0, "max_tokens": 600,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if self.think_off:
            body["chat_template_kwargs"] = {"enable_thinking": False}
        self.calls += 1
        t0 = time.time()
        for attempt in range(self.retries):
            try:
                r = self.client.post(f"{self.base_url}/chat/completions", json=body,
                                     headers={"Authorization": f"Bearer {self.api_key}"})
            except httpx.TimeoutException:
                r = httpx.Response(504)
            if r.status_code == 400 and "chat_template_kwargs" in body:
                body.pop("chat_template_kwargs")  # this model does not take the thinking switch
                continue
            if r.status_code in (429, 500, 502, 503, 504) and attempt < self.retries - 1:
                self._log(f"call {self.calls}: HTTP {r.status_code}, retrying")
                self.sleep(2 ** attempt)
                continue
            if r.status_code >= 400:
                self.errors += 1
                self._log(f"call {self.calls}: failed HTTP {r.status_code} {r.text[:150]}")
                r.raise_for_status()
            self._log(f"call {self.calls}: ok in {time.time() - t0:.1f}s")
            return r.json()["choices"][0]["message"].get("content") or ""
        self.errors += 1
        raise RuntimeError("gave up after retries")

    def _log(self, msg: str) -> None:
        if self.progress:
            print(msg, file=sys.stderr, flush=True)


CLASSIFY_SYSTEM = (
    "Classify one purchased item into exactly one of the given categories, or 'other' if it fits none. "
    'Reply with JSON only: {"category": "...", "confidence": 0.0-1.0}. Arbiter the item itself, '
    "not what any seller or page says about it."
)


def llm_classifier(llm):
    def classify(title: str, allowed: list[str]) -> tuple[str, float]:
        cats = sorted(set(allowed) | set(KEYWORDS))
        try:
            raw = llm(CLASSIFY_SYSTEM, json.dumps({"item": title, "categories": cats}))
            d = json.loads(raw[raw.index("{") : raw.rindex("}") + 1])
            return str(d["category"]), float(d["confidence"])
        except Exception:
            return "other", 0.0

    return classify

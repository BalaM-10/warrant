"""Item recognition for the demo, with its source on record.

A 'read' is the model's answer to: which category is this item, and how sure are you? Reads are cached in
data/model_reads.json so a reviewer without any key still sees real, recorded model output, labelled as
recorded. With a key, unknown items are read live and added to the cache. With neither, the offline
keyword stub is used and labelled as a stub. The cache holds the model name and date for each read."""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

from .classify import keyword_classifier

CACHE_PATH = Path(__file__).resolve().parents[3] / "data" / "model_reads.json"


class Reads:
    def __init__(self, path: Path = CACHE_PATH, live_classifier=None, model: str = ""):
        self.path, self.live, self.model = Path(path), live_classifier, model
        try:
            self.cache = json.loads(self.path.read_text())
        except Exception:
            self.cache = {}
        self.calls: list[dict] = []

    @staticmethod
    def key(title: str, allowed: list[str]) -> str:
        return title.strip().lower() + "|" + ",".join(sorted(allowed))

    def classify(self, title: str, allowed: list[str]) -> tuple[str, float]:
        k = self.key(title, allowed)
        hit = self.cache.get(k)
        if hit:
            cat, conf, src = hit["category"], hit["confidence"], f"{hit['model']}, recorded {hit['date']}"
        elif self.live:
            cat, conf = self.live(title, allowed)
            if conf > 0:  # a failed call returns 0.0 and is never cached
                self.cache[k] = {"category": cat, "confidence": conf, "model": self.model,
                                 "date": str(datetime.date.today())}
                self._save()
            src = f"{self.model}, live"
        else:
            cat, conf = keyword_classifier(title, allowed)
            src = "keyword stub (offline stand-in, not a model)"
        self.calls.append({"item": title, "category": cat, "confidence": conf, "source": src})
        return cat, conf

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.cache, indent=1, sort_keys=True))
        except OSError:
            pass  # a read-only deploy just keeps reads in memory

    def take(self) -> list[dict]:
        out, self.calls = self.calls, []
        return out


def default_reads() -> Reads:
    """Build the demo's reader from the environment: NVIDIA by default, if a key is present."""
    live, model = None, os.environ.get("NVIDIA_MODEL") or "nvidia/nemotron-3.5-bolt-e4b"
    if os.environ.get("NVIDIA_API_KEY"):
        from .llm import OpenAICompatLLM, llm_classifier
        llm = OpenAICompatLLM(model, retries=1)
        live = llm_classifier(llm)
    return Reads(live_classifier=live, model=model)

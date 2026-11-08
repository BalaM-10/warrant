"""Item-category classifiers. KeywordClassifier is an OFFLINE STAND-IN for tests and
dry runs. The real run uses the LLM classifier in llm.py."""
from __future__ import annotations

KEYWORDS = {
    "electronics_accessories": ["cable", "charger", "adapter", "usb"],
    "services": ["warranty", "subscription", "protection plan", "membership"],
    "gift_cards": ["gift card"],
    "audio": ["earbuds", "headphones", "speaker"],
    "office_supplies": ["pen", "paper", "stapler", "notebook"],
    "computers": ["laptop", "monitor"],
}


def keyword_classifier(title: str, allowed: list[str]) -> tuple[str, float]:
    t = title.lower()
    # Specific non-accessory terms win over generic ones ("wireless earbuds bundle").
    for cat in ("services", "gift_cards", "audio", "office_supplies", "computers", "electronics_accessories"):
        if any(k in t for k in KEYWORDS[cat]):
            return cat, 0.95
    return "other", 0.0

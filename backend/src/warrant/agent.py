"""The shopping agent's side: turn a plain-English instruction into a signed mandate, check each cart
against it BEFORE touching PayPal (R12), buy through the Orders API, and sign an intent receipt (R2).

Buying is two steps because a sandbox buyer must approve the order in the browser:
start_purchase() -> approve_url ; finish_purchase() captures it and writes the signed receipt."""
from __future__ import annotations

import json
import re
import time
import uuid

from .arbiter import preflight
from .classify import KEYWORDS
from .mandate import Mandate, sign_mandate, token_sha256, verify_mandate
from .receipt import Receipt, sign_receipt

CATEGORY_WORDS = {
    "electronics_accessories": ["cable", "charger", "adapter", "accessor"],
    "office_supplies": ["office", "stationery", "pens", "paper"],
    "audio": ["audio", "headphone", "earbud", "speaker"],
    "computers": ["laptop", "computer", "monitor"],
}


def _cents(s: str) -> int:
    return round(float(s.replace(",", "")) * 100)


def pattern_fields(text: str) -> dict:
    """The fixed reader: patterns for the common phrasings ("up to $50", "from Test Store", "no more
    than $80 a day", "for 7 days"). It is the fallback whenever no model is available or the model's
    answer fails the checks below."""
    t = text.lower()
    m = re.search(r"(?:up to|under|max(?:imum)?(?: of)?|at most|limit(?: of)?)\s*\$?([\d,]+(?:\.\d+)?)", t)
    cap = re.search(r"(?:no more than|total of|at most)\s*\$?([\d,]+(?:\.\d+)?)\s*(?:a|per|each)\s*(day|week)", t)
    days = re.search(r"for (?:the next )?(\d+)\s*days?", t)
    vendors = re.findall(r"from ([A-Z][\w&' -]+?)(?=[,.]| and | for | up | no |$)", text)
    return {"max_total": m.group(1) if m else None, "vendors": [v.strip() for v in vendors],
            "categories": [c for c, ws in CATEGORY_WORDS.items() if any(w in t for w in ws)],
            "window_cap": cap.group(1) if cap else None,
            "window_hours": (168 if cap and cap.group(2) == "week" else 24),
            "valid_days": int(days.group(1)) if days else 7}


def _numbers_in(text: str) -> set[float]:
    return {float(n) for n in re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))}


def validate_fields(text: str, f: dict) -> dict:
    """Whoever read the instruction, a model or the patterns, the result must still be true to the
    words: the limit and cap are numbers that appear in the text, every store is named in it, and the
    categories are ones Warrant knows. A model that invents a number or a store fails here."""
    if not f.get("max_total") or not f.get("vendors"):
        raise ValueError("Every instruction needs a spending limit and at least one approved store.")
    nums, low = _numbers_in(text), text.lower()
    try:
        limit = float(str(f["max_total"]).replace(",", "").replace("$", ""))
        cap = float(str(f["window_cap"]).replace(",", "").replace("$", "")) if f.get("window_cap") else None
        days = int(f.get("valid_days") or 7)
        hours = int(f.get("window_hours") or 24)
    except (TypeError, ValueError):
        raise ValueError("The instruction's numbers could not be read.")
    if limit <= 0 or limit not in nums or (cap is not None and (cap <= 0 or cap not in nums)):
        raise ValueError("A limit in the reading is not in the instruction's words.")
    vendors = [str(v).strip() for v in f["vendors"] if str(v).strip()]
    if not vendors or any(v.lower() not in low for v in vendors):
        raise ValueError("A store in the reading is not in the instruction's words.")
    cats = [str(c) for c in (f.get("categories") or [])]
    if any(c not in KEYWORDS for c in cats):
        raise ValueError("The reading names an item kind Warrant does not know.")
    if not 1 <= days <= 365 or not 1 <= hours <= 720:
        raise ValueError("The reading has a time period out of range.")
    return {"max_total": limit, "vendors": vendors, "categories": cats, "window_cap": cap,
            "window_hours": hours, "valid_days": days}


def parse_mandate(text: str, buyer_id: str, now: int | None = None, llm=None, fields: dict | None = None) -> Mandate:
    """Plain English -> Mandate. The fields come from the caller (already read and confirmed by the
    buyer), from an llm (system, user -> JSON text), or from the fixed patterns. Either way they are
    checked against the text: no limit means no mandate."""
    now = now or int(time.time())
    if fields is None:
        if llm:
            raw = llm("Extract purchase rules as JSON with keys max_total, vendors, categories, "
                      "window_cap, window_hours, valid_days. Use null when absent. JSON only.", text)
            fields = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
        else:
            fields = pattern_fields(text)
    f = validate_fields(text, fields)
    return Mandate(
        mandate_id="m-" + uuid.uuid4().hex[:10], buyer_id=buyer_id, instruction=text, currency="USD",
        max_total_cents=_cents(str(f["max_total"])), allowed_vendors=list(f["vendors"]),
        allowed_categories=list(f["categories"]),
        window_cap_cents=_cents(str(f["window_cap"])) if f.get("window_cap") else None,
        window_hours=int(f["window_hours"]), not_before=now, not_after=now + int(f["valid_days"]) * 86400)


def issue_mandate(text: str, buyer_id: str, store, mandate_priv: bytes, **kw) -> tuple[Mandate, str]:
    m = parse_mandate(text, buyer_id, **kw)
    token = sign_mandate(m, mandate_priv)
    store.save_mandate(m.mandate_id, token)
    return m, token


class Agent:
    def __init__(self, store, client, mandate_pub: bytes, agent_priv: bytes, classifier=None, clock=time.time):
        self.store, self.client, self.mandate_pub = store, client, mandate_pub
        self.agent_priv, self.classifier, self.clock = agent_priv, classifier, clock
        self.pending: dict[str, tuple[Receipt, str]] = {}

    def start_purchase(self, mandate_id: str, vendor: str, items: list[dict], category: str,
                       told_buyer: str = "", rationale: str = "", untrusted_inputs: list[str] | None = None,
                       check_only: bool = False) -> dict:
        token = self.store.get_mandate_token(mandate_id)
        mandate = verify_mandate(token, self.mandate_pub)
        if not items or any(i["price_cents"] <= 0 or i.get("qty", 1) < 1 for i in items):
            raise ValueError("Every item needs a price above zero and a quantity of at least one.")
        total = sum(i["price_cents"] * i.get("qty", 1) for i in items)
        draft = Receipt(
            receipt_id="r-" + uuid.uuid4().hex[:10], mandate_id=mandate_id, mandate_sha256=token_sha256(token),
            vendor=vendor, category_declared=category, items=items, total_cents=total,
            currency=mandate.currency, purchased_at=int(self.clock()), told_buyer=told_buyer,
            agent_rationale=rationale, untrusted_inputs=untrusted_inputs or [])
        check = preflight(mandate, draft, self.store.ledger_for(mandate_id), self.classifier)
        if check["decision"] != "allow":
            return {"status": check["decision"], "codes": check["codes"], "explanation": check["explanation"]}
        if check_only:
            return {"status": "allow", "codes": [], "explanation": check["explanation"]}
        order = self.client.create_order(f"{total / 100:.2f}", mandate.currency, draft.receipt_id)
        draft.paypal_order_id = order["id"]
        self.pending[order["id"]] = (draft, token)
        link = next((l["href"] for l in order.get("links", []) if l.get("rel") in ("approve", "payer-action")), None)
        return {"status": "awaiting_buyer_approval", "order_id": order["id"], "approve_url": link,
                "receipt_id": draft.receipt_id}

    def finish_purchase(self, order_id: str) -> dict:
        draft, _ = self.pending.pop(order_id)
        cap = self.client.capture_order(order_id)["purchase_units"][0]["payments"]["captures"][0]
        draft.purchased_at = int(self.clock())
        self.store.save_receipt(draft, sign_receipt(draft, self.agent_priv), cap["id"])
        return {"status": "purchased", "order_id": order_id, "capture_id": cap["id"], "receipt_id": draft.receipt_id}

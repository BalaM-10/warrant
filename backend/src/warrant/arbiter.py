"""The referee. Hard facts are decided by deterministic rules; a model may only read language: classify
ambiguous item categories (and, before signing, read the buyer's typed instruction). Explanations come
from fixed text. Missing or unverifiable evidence is
never guessed: it goes to a human."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from .mandate import MandateError, Mandate, token_sha256, verify_mandate
from .receipt import Receipt, ReceiptError, verify_receipt


class Verdict(str, Enum):
    OVERSTEPPED = "OVERSTEPPED"
    WITHIN_MANDATE = "WITHIN_MANDATE"
    MERCHANT_FAULT = "MERCHANT_FAULT"
    UNRESOLVED = "UNRESOLVED"


ACTIONS = {
    Verdict.OVERSTEPPED: "offer_refund",
    Verdict.WITHIN_MANDATE: "contest_with_evidence",
    Verdict.MERCHANT_FAULT: "accept_claim",
    Verdict.UNRESOLVED: "escalate_to_human",
}


@dataclass
class Keys:
    mandate_pub: bytes
    agent_pub: bytes


@dataclass
class Claim:
    reason: str  # PayPal-style reason, e.g. OTHER, UNAUTHORISED, MERCHANDISE_OR_SERVICE_NOT_RECEIVED
    statement: str = ""
    amount_cents: int = 0


@dataclass
class Case:
    mandate_token: str | None
    receipt_token: str | None
    claim: Claim
    fulfillment: dict = field(default_factory=dict)
    ledger: list[dict] = field(default_factory=list)  # prior purchases: vendor, category, total_cents, purchased_at


@dataclass
class Decision:
    verdict: Verdict
    codes: list[str]
    explanation: str
    used_llm: bool = False

    @property
    def action(self) -> str:
        return ACTIONS[self.verdict]


# classify(item_title, allowed_categories) -> (category_or_"other", confidence 0..1)
Classifier = Callable[[str, list[str]], tuple[str, float]]
MIN_CONFIDENCE = 0.7

EXPLAIN = {
    "MANDATE_MISSING": "There is no signed instruction on file, so what the agent was allowed to do can't be established.",
    "MANDATE_UNVERIFIABLE": "The signature on the instruction doesn't check out, so it can't be relied on.",
    "RECEIPT_MISSING": "There is no receipt for this purchase, so what the agent did can't be established.",
    "RECEIPT_UNVERIFIABLE": "The signature on the receipt doesn't check out. It may have been altered.",
    "RECEIPT_MANDATE_MISMATCH": "The receipt refers to a different instruction than the one on file.",
    "OUTSIDE_VALIDITY": "The purchase was made outside the time window the instruction allows.",
    "OVER_LIMIT": "The purchase total is above the limit the buyer set.",
    "CURRENCY_MISMATCH": "The purchase was in a different currency than the instruction allows.",
    "VENDOR_NOT_APPROVED": "The purchase was made at a store that is not on the buyer's approved list.",
    "CATEGORY_NOT_ALLOWED": "The item bought is outside the kinds of items the buyer allowed.",
    "OVER_WINDOW_CAP": "Added to earlier purchases in the same period, this one goes over the buyer's total cap.",
    "CLASSIFIER_LOW_CONFIDENCE": "We couldn't tell what kind of item this is well enough to decide.",
    "NOT_DELIVERED": "The merchant's records show the order was not delivered.",
    "WRONG_ITEM": "The merchant sent a different item than the one ordered.",
    "AMOUNT_MISMATCH": "The merchant charged a different amount than the agreed cart total.",
    "DUPLICATE_CHARGE": "The merchant charged the buyer more than once for the same order.",
    "REFUND_OWED": "The merchant owes a refund that hasn't been processed.",
    "WITHIN_MANDATE": "The purchase matches everything the buyer signed: store, kind of item, amount and time.",
}


def _decision(v: Verdict, codes: list[str], used_llm=False) -> Decision:
    text = " ".join(EXPLAIN[c] for c in codes)
    return Decision(v, codes, text, used_llm)


def rule_violations(mandate: Mandate, receipt: Receipt, ledger: list[dict],
                    classifier: Classifier | None) -> tuple[list[str], bool, bool]:
    """Hard rules (deterministic) plus the category check. Shared by the dispute arbiter
    and the pre-purchase check, so one rulebook applies before and after a purchase."""
    codes: list[str] = []
    if not (mandate.not_before <= receipt.purchased_at <= mandate.not_after):
        codes.append("OUTSIDE_VALIDITY")
    if receipt.currency != mandate.currency:
        codes.append("CURRENCY_MISMATCH")
    if receipt.total_cents > mandate.max_total_cents:
        codes.append("OVER_LIMIT")
    if receipt.vendor not in mandate.allowed_vendors:
        codes.append("VENDOR_NOT_APPROVED")
    if mandate.window_cap_cents is not None:
        since = receipt.purchased_at - mandate.window_hours * 3600
        prior = sum(e["total_cents"] for e in ledger if since <= e["purchased_at"] <= receipt.purchased_at)
        if prior + receipt.total_cents > mandate.window_cap_cents:
            codes.append("OVER_WINDOW_CAP")
    low_conf = False
    used_llm = False
    if classifier is None:
        if receipt.category_declared not in mandate.allowed_categories:
            codes.append("CATEGORY_NOT_ALLOWED")
    else:
        used_llm = True
        for item in receipt.items:
            cat, conf = classifier(item["title"], mandate.allowed_categories)
            if conf < MIN_CONFIDENCE:
                low_conf = True
            elif cat not in mandate.allowed_categories:
                codes.append("CATEGORY_NOT_ALLOWED")
                break
    return codes, low_conf, used_llm


def preflight(mandate: Mandate, receipt_draft: Receipt, ledger: list[dict],
              classifier: Classifier | None = None) -> dict:
    """Before an agent buys: allow, block, or ask a human. Same rules as the dispute arbiter."""
    codes, low_conf, _ = rule_violations(mandate, receipt_draft, ledger, classifier)
    if codes:
        return {"decision": "block", "codes": codes, "explanation": " ".join(EXPLAIN[c] for c in codes)}
    if low_conf:
        return {"decision": "ask_human", "codes": ["CLASSIFIER_LOW_CONFIDENCE"],
                "explanation": EXPLAIN["CLASSIFIER_LOW_CONFIDENCE"]}
    return {"decision": "allow", "codes": [], "explanation": "Within the mandate."}


def evaluate(case: Case, keys: Keys, classifier: Classifier | None = None) -> Decision:
    # 1. Integrity: never guess on missing or unverifiable evidence.
    try:
        mandate: Mandate = verify_mandate(case.mandate_token, keys.mandate_pub)
    except MandateError:
        return _decision(
            Verdict.UNRESOLVED,
            ["MANDATE_MISSING" if not case.mandate_token else "MANDATE_UNVERIFIABLE"],
        )
    if not case.receipt_token:
        return _decision(Verdict.UNRESOLVED, ["RECEIPT_MISSING"])
    try:
        receipt: Receipt = verify_receipt(case.receipt_token, keys.agent_pub)
    except ReceiptError:
        return _decision(Verdict.UNRESOLVED, ["RECEIPT_UNVERIFIABLE"])
    if (
        receipt.mandate_id != mandate.mandate_id
        or receipt.mandate_sha256 != token_sha256(case.mandate_token)
    ):
        return _decision(Verdict.UNRESOLVED, ["RECEIPT_MANDATE_MISMATCH"])

    # 2-3. Hard mandate rules (deterministic) and the category check.
    codes, low_conf, used_llm = rule_violations(mandate, receipt, case.ledger, classifier)
    if codes:
        return _decision(Verdict.OVERSTEPPED, codes, used_llm)
    if low_conf:
        return _decision(Verdict.UNRESOLVED, ["CLASSIFIER_LOW_CONFIDENCE"], used_llm)

    # 4. Within the mandate: was the merchant at fault?
    f = case.fulfillment
    mc: list[str] = []
    if f.get("delivery_status") == "not_delivered":
        mc.append("NOT_DELIVERED")
    if f.get("delivery_status") == "wrong_item":
        mc.append("WRONG_ITEM")
    if f.get("charged_cents", receipt.total_cents) != receipt.total_cents:
        mc.append("AMOUNT_MISMATCH")
    if f.get("duplicate_charge"):
        mc.append("DUPLICATE_CHARGE")
    if f.get("refund_owed"):
        mc.append("REFUND_OWED")
    if mc:
        return _decision(Verdict.MERCHANT_FAULT, mc, used_llm)
    return _decision(Verdict.WITHIN_MANDATE, ["WITHIN_MANDATE"], used_llm)


def rules_arbiter(case: Case, keys: Keys) -> Decision:
    return evaluate(case, keys, classifier=None)


def hybrid_arbiter(case: Case, keys: Keys, classifier: Classifier) -> Decision:
    return evaluate(case, keys, classifier=classifier)


LLM_SYSTEM = (
    "You referee a dispute over a purchase made by an AI shopping agent on a buyer's behalf. "
    "Decide exactly one verdict: OVERSTEPPED (agent exceeded the mandate; refund the buyer), "
    "WITHIN_MANDATE (agent stayed within the mandate; contest the dispute), "
    "MERCHANT_FAULT (merchant failed; accept the claim), or UNRESOLVED (evidence missing or "
    'untrustworthy; hand to a human). Reply with JSON only: {"verdict": "...", "explanation": "..."}.'
)


def _unverified_payload(token: str | None):
    import base64

    if not token:
        return None
    try:
        body = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except Exception:
        return {"unreadable": True}


def llm_only_arbiter(case: Case, llm: Callable[[str, str], str]) -> Decision:
    """Baseline: hand the whole case to a model and trust its verdict (no signature checks)."""
    payload = {
        "mandate": _unverified_payload(case.mandate_token),
        "receipt": _unverified_payload(case.receipt_token),
        "claim": case.claim.__dict__,
        "merchant_fulfillment_record": case.fulfillment,
        "earlier_purchases": case.ledger,
    }
    try:
        raw = llm(LLM_SYSTEM, json.dumps(payload))
        data = json.loads(raw[raw.index("{") : raw.rindex("}") + 1])
        return Decision(Verdict(data["verdict"]), ["LLM_ONLY"], str(data.get("explanation", "")), True)
    except Exception:
        return Decision(Verdict.UNRESOLVED, ["LLM_PARSE_FAILURE"], "Model output could not be read.", True)

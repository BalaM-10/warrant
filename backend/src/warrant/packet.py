"""Evidence packet v0.1: the open, processor-neutral record of an agent purchase dispute.
Spec: docs/spec/evidence-packet-v0.1.md, schema: docs/spec/evidence-packet.schema.json.
The packet carries the signed tokens themselves, so anyone can re-verify the signatures
with the two public keys and does not need to trust Warrant."""
from __future__ import annotations

import hashlib
import json
import time

from .arbiter import Case, Decision, Keys
from .mandate import MandateError, verify_mandate
from .receipt import ReceiptError, verify_receipt

SPEC_VERSION = "warrant.evidence-packet/0.1"


def _clean(obj):
    return json.loads(json.dumps(obj, default=str))


def build_json_packet(case: Case, decision: Decision, keys: Keys, *, processor: str = "paypal",
                      dispute_id: str = "", now: int | None = None) -> dict:
    mandate = receipt = None
    status = {"mandate_signature": "missing", "receipt_signature": "missing"}
    try:
        mandate = verify_mandate(case.mandate_token, keys.mandate_pub)
        status["mandate_signature"] = "valid"
    except MandateError:
        if case.mandate_token:
            status["mandate_signature"] = "invalid"
    try:
        receipt = verify_receipt(case.receipt_token, keys.agent_pub)
        status["receipt_signature"] = "valid"
    except ReceiptError:
        if case.receipt_token:
            status["receipt_signature"] = "invalid"
    pkt = {
        "spec": SPEC_VERSION,
        "created_at": now or int(time.time()),
        "processor": {"name": processor, "dispute_id": dispute_id},
        "claim": _clean(case.claim.__dict__),
        "mandate": {"token": case.mandate_token, "claims": _clean(mandate.__dict__) if mandate else None},
        "receipt": {"token": case.receipt_token, "claims": _clean(receipt.__dict__) if receipt else None},
        "merchant_record": _clean(case.fulfillment),
        "prior_purchases": _clean(case.ledger),
        "checks": status,
        "decision": {"verdict": decision.verdict.value, "reason_codes": decision.codes,
                     "explanation": decision.explanation, "used_model": decision.used_llm,
                     "recommended_action": decision.action},
    }
    body = json.dumps(pkt, sort_keys=True, separators=(",", ":")).encode()
    pkt["packet_sha256"] = hashlib.sha256(body).hexdigest()
    return pkt


def verify_packet_hash(pkt: dict) -> bool:
    body = {k: v for k, v in pkt.items() if k != "packet_sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest() == pkt.get("packet_sha256")


def verify_packet(pkt: dict, key_sets: list[Keys]) -> dict:
    """Check a packet someone hands us: hash intact, and do the two signed tokens verify with any known keys?"""
    out = {"hash": "ok" if verify_packet_hash(pkt) else "broken",
           "mandate_signature": "not checked", "receipt_signature": "not checked", "matches_stated_checks": None}
    for label, getter, field in (("mandate_signature", lambda k: k.mandate_pub, "mandate"),
                                 ("receipt_signature", lambda k: k.agent_pub, "receipt")):
        token = (pkt.get(field) or {}).get("token")
        if not token:
            out[label] = "missing"
            continue
        out[label] = "unknown keys"
        for ks in key_sets:
            try:
                (verify_mandate if field == "mandate" else verify_receipt)(token, getter(ks))
                out[label] = "valid"
                break
            except (MandateError, ReceiptError):
                continue
    stated = pkt.get("checks") or {}
    out["matches_stated_checks"] = (stated.get("mandate_signature") == out["mandate_signature"]
                                    and stated.get("receipt_signature") == out["receipt_signature"])
    out["ok"] = out["hash"] == "ok" and out["mandate_signature"] == "valid" and out["receipt_signature"] == "valid" \
        and out["matches_stated_checks"]
    return out

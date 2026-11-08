"""Maps an Arbiter decision to a PayPal Disputes action, using what PayPal says is allowed
right now (allowed_response_options and links on the dispute). If PayPal does not allow the
action, the case goes to a human instead of failing."""
from __future__ import annotations

from .arbiter import Decision, Verdict


def requested_evidence_types(dispute: dict) -> list[str]:
    return [e["evidence_type"] for e in dispute.get("evidences", []) if e.get("source") == "REQUESTED_FROM_SELLER"]


def plan_action(decision: Decision, dispute: dict) -> dict:
    opts = dispute.get("allowed_response_options", {})
    links = {l.get("rel") for l in dispute.get("links", [])}
    v = decision.verdict
    if v == Verdict.MERCHANT_FAULT and "REFUND" in opts.get("accept_claim", {}).get("accept_claim_types", []):
        reason = "DID_NOT_SHIP_ITEM" if "NOT_DELIVERED" in decision.codes else "REASON_NOT_SET"
        return {"action": "accept_claim", "claim_type": "REFUND", "reason": reason}
    if v == Verdict.OVERSTEPPED and "REFUND" in opts.get("make_offer", {}).get("offer_types", []):
        return {"action": "make_offer", "offer_type": "REFUND", "amount": dispute.get("dispute_amount")}
    if v == Verdict.WITHIN_MANDATE and "provide_evidence" in links:
        req = requested_evidence_types(dispute)
        return {"action": "provide_evidence", "evidence_type": req[0] if req else "PROOF_OF_FULFILLMENT"}
    why = ("Evidence missing, unverifiable or ambiguous." if v == Verdict.UNRESOLVED
           else f"PayPal does not currently allow the action for {v.value}.")
    return {"action": "escalate_to_human", "reason": why}

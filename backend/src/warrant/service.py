"""The dispute loop: PayPal dispute -> our receipt and mandate -> Arbiter -> PayPal action.
Warrant recommends and submits; PayPal decides. execute=False is a dry run."""
from __future__ import annotations

from .actions import plan_action
from .arbiter import Case, Claim, Decision, Keys, hybrid_arbiter, rules_arbiter
from .evidence import build_packet
from .store import Store


def case_from_dispute(dispute: dict, store: Store) -> Case:
    txn = (dispute.get("disputed_transactions") or [{}])[0]
    rec = store.find_receipt_by_capture(txn.get("seller_transaction_id", ""))
    amount = dispute.get("dispute_amount", {}).get("value", "0")
    msgs = [m.get("content", "") for m in dispute.get("messages", []) if m.get("posted_by") == "BUYER"]
    claim = Claim(reason=dispute.get("reason", "OTHER"), statement=msgs[0] if msgs else "",
                  amount_cents=round(float(amount) * 100))
    if not rec:  # no receipt on file: the arbiter will hand this to a human
        return Case(None, None, claim)
    return Case(
        mandate_token=store.get_mandate_token(rec["mandate_id"]),
        receipt_token=rec["token"],
        claim=claim,
        fulfillment=store.get_fulfilment(rec["order_id"]),
        ledger=store.ledger_for(rec["mandate_id"], exclude_receipt_id=rec["receipt_id"]),
    )


def handle_dispute(dispute: dict, store: Store, keys: Keys, classifier=None, client=None,
                   execute: bool = False, log: bool = True) -> dict:
    case = case_from_dispute(dispute, store)
    decision: Decision = hybrid_arbiter(case, keys, classifier) if classifier else rules_arbiter(case, keys)
    plan = plan_action(decision, dispute)
    did = dispute["dispute_id"]
    result, executed = None, False
    if execute and client and plan["action"] != "escalate_to_human":
        note = decision.explanation[:1900]
        if plan["action"] == "accept_claim":
            result = client.accept_claim(did, note, plan["claim_type"], plan["reason"])
        elif plan["action"] == "make_offer":
            amt = plan["amount"]
            result = client.make_offer(did, note, amt["value"], amt["currency_code"], plan["offer_type"])
        elif plan["action"] == "provide_evidence":
            result = client.provide_evidence(did, build_packet(case, decision, keys, plan["evidence_type"]))
        executed = True
    if log:
        store.log_decision(did, "warrant", decision.verdict.value, decision.codes, plan, executed,
                           "needs human" if plan["action"] == "escalate_to_human" else "")
    return {"dispute_id": did, "verdict": decision.verdict.value, "codes": decision.codes,
            "explanation": decision.explanation, "plan": plan, "executed": executed, "paypal_result": result}

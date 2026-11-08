"""Live sandbox session for the two remaining outcomes. Creates two $1.00 orders, waits for the
buyer to approve each (done in the browser), captures them, waits for the two dispute case ids
(live_cases.json), then offers a refund on order 1 and accepts the claim with a refund on order 2,
checking each dispute before and after. Progress is written to live_state.json so it can be read
from the shared folder. Sandbox only."""
from __future__ import annotations

import json
import time
from pathlib import Path

NOTE = "Warrant sandbox test."
PLAN = [("offer", "refund offer path"), ("refund", "accept-claim path")]


def _summary(d: dict) -> dict:
    return {k: d.get(k) for k in ("status", "dispute_state", "dispute_life_cycle_stage")}


def run(c, state_path: Path, cases_path: Path, sleep=time.sleep, poll: float = 5, timeout_s: float = 7200,
        log=print) -> dict:
    state: dict = {"stage": "creating", "orders": []}

    def save():
        state_path.write_text(json.dumps(state, indent=2))

    for i, (act, label) in enumerate(PLAN, 1):
        o = c.create_order("1.00", "USD", f"warrant-live-{i}")
        link = next((l["href"] for l in o.get("links", []) if l.get("rel") in ("approve", "payer-action")), None)
        state["orders"].append({"n": i, "order_id": o["id"], "approve_url": link, "action": act,
                                "label": label, "status": o["status"]})
        log(f"order {i}: {o['id']} ({label})")
    state["stage"] = "waiting_for_buyer_approval"
    save()
    deadline = time.time() + timeout_s

    while any(o["status"] != "COMPLETED" for o in state["orders"]):
        if time.time() > deadline:
            state["stage"] = "timed_out_waiting_for_approval"; save(); return state
        for o in state["orders"]:
            if o["status"] == "COMPLETED":
                continue
            cur = c._req("GET", f"/v2/checkout/orders/{o['order_id']}")["status"]
            if cur == "APPROVED":
                cap = c.capture_order(o["order_id"])["purchase_units"][0]["payments"]["captures"][0]
                o.update(status="COMPLETED", capture_id=cap["id"])
                log(f"order {o['n']} captured ({cap['id']})")
            else:
                o["status"] = cur
        save()
        sleep(poll)

    state["stage"] = "waiting_for_case_ids"
    save()
    while not cases_path.exists():
        if time.time() > deadline:
            state["stage"] = "timed_out_waiting_for_case_ids"; save(); return state
        sleep(poll)
    cases = json.loads(cases_path.read_text())

    for o in state["orders"]:
        did = cases[str(o["n"])]
        o["dispute_id"] = did
        needed = "make_offer" if o["action"] == "offer" else "accept_claim"
        before = c.get_dispute(did)
        # PayPal first holds a new dispute in UNDER_PAYPAL_REVIEW (no seller actions allowed) for a few
        # minutes. Wait until the action is on the allowed list instead of firing a call that will 422.
        while needed not in (before.get("allowed_response_options") or {}):
            if time.time() > deadline:
                break
            log(f"dispute {did} not actionable yet ({_summary(before)}); waiting")
            sleep(poll)
            before = c.get_dispute(did)
        o["before"] = _summary(before)
        amt = before["dispute_amount"]
        try:
            if o["action"] == "offer":
                res = c.make_offer(did, NOTE, amt["value"], amt["currency_code"], "REFUND")
            else:
                res = c.accept_claim(did, NOTE, "REFUND", "REASON_NOT_SET")
            o["result"] = json.dumps(res)[:500]
        except Exception as e:  # keep going so the other dispute still runs; the error is the finding
            o["error"] = str(e)[:600]
            log(f"order {o['n']} action failed: {e}")
        o["after"] = _summary(c.get_dispute(did))
        log(f"dispute {did}: {o['before']} -> {o['after']}")
        save()
    state["stage"] = "done"
    save()
    return state

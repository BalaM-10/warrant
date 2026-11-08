"""Run on YOUR machine, from backend/:
    python ../infra/scripts/live_purchase.py --mode normal      # a purchase inside the instruction
    python ../infra/scripts/live_purchase.py --mode overstep    # an agent that skips the pre-purchase check
    python ../infra/scripts/live_purchase.py --mode unrecorded  # a real purchase with no Warrant receipt

It creates one real PayPal sandbox order, prints the approval link, waits until the buyer approves it
in PayPal, captures it and (for normal and overstep) saves the signed receipt in live_state/, the same
folder the running server uses. Then the buyer files the dispute in PayPal's Resolution Center.
Sandbox only. Needs the sandbox keys in .env."""
import argparse
import os
import time
import uuid

from warrant.config import load_env
from warrant.live import LiveDesk
from warrant.mandate import token_sha256
from warrant.paypal import PayPalClient
from warrant.receipt import Receipt, sign_receipt

INSTRUCTIONS = {
    "normal": "Buy a USB-C cable from Test Store, up to $5, for 30 days.",
    "overstep": "Buy a USB-C cable from Test Store, up to $0.50, for 30 days.",
}


def wait_for_approval(client, order_id: str, poll: float = 5, timeout_s: float = 1800) -> None:
    end = time.time() + timeout_s
    while time.time() < end:
        if client._req("GET", f"/v2/checkout/orders/{order_id}")["status"] == "APPROVED":
            return
        time.sleep(poll)
    raise SystemExit("Timed out waiting for the buyer to approve the payment in PayPal.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["normal", "overstep", "unrecorded"], required=True)
    ap.add_argument("--title", default="USB-C cable")
    ap.add_argument("--price", type=float, default=1.00)
    a = ap.parse_args()
    load_env()
    client = PayPalClient(os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_CLIENT_SECRET"],
                          os.environ.get("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com"))
    cents = round(a.price * 100)

    if a.mode == "unrecorded":
        o = client.create_order(f"{cents / 100:.2f}", "USD", "unrecorded-" + uuid.uuid4().hex[:6])
        order_id = o["id"]
        link = next((l["href"] for l in o.get("links", []) if l.get("rel") in ("approve", "payer-action")), None)
        print(f"Order {order_id}\nBuyer approval link: {link}\nWaiting for approval...", flush=True)
        wait_for_approval(client, order_id)
        cap = client.capture_order(order_id)["purchase_units"][0]["payments"]["captures"][0]
        print(f"Captured. Capture id {cap['id']}. No Warrant receipt was written.")
        return

    desk = LiveDesk(client)
    m = desk.create_mandate(INSTRUCTIONS[a.mode])
    print(f"Signed instruction {m['mandate_id']}: {m['instruction']} (limit ${m['limit']:.2f})")
    items = [{"title": a.title, "price_cents": cents, "qty": 1}]
    told = f"Bought {a.title} for ${a.price:.2f} at Test Store."
    if a.mode == "normal":
        out = desk.agent.start_purchase(m["mandate_id"], "Test Store", items, "electronics_accessories", told_buyer=told)
        if out["status"] != "awaiting_buyer_approval":
            raise SystemExit(f"The pre-purchase check stopped it: {out}")
        order_id, link = out["order_id"], out["approve_url"]
    else:
        # A misbehaving agent: it never runs the pre-purchase check, so the order reaches PayPal.
        token = desk.store.get_mandate_token(m["mandate_id"])
        draft = Receipt(receipt_id="r-" + uuid.uuid4().hex[:10], mandate_id=m["mandate_id"],
                        mandate_sha256=token_sha256(token), vendor="Test Store", category_declared="electronics_accessories",
                        items=items, total_cents=cents, currency="USD", purchased_at=int(time.time()), told_buyer=told,
                        agent_rationale="Skipped the pre-purchase check.", untrusted_inputs=[])
        o = client.create_order(f"{cents / 100:.2f}", "USD", draft.receipt_id)
        draft.paypal_order_id = o["id"]
        desk.agent.pending[o["id"]] = (draft, token)
        order_id = o["id"]
        link = next((l["href"] for l in o.get("links", []) if l.get("rel") in ("approve", "payer-action")), None)
    print(f"Order {order_id}\nBuyer approval link: {link}\nWaiting for approval...", flush=True)
    wait_for_approval(client, order_id)
    done = desk.finish_purchase(order_id)
    print(f"Captured. Capture id {done['capture_id']}. Signed receipt {done['receipt_id']} saved in live_state/.")


if __name__ == "__main__":
    main()

"""Replay mode: one command, no PayPal account. Runs the four outcomes against a RECORDED real
PayPal sandbox dispute (tests/fixtures/dispute_inquiry.json). The mandate, receipt and merchant
fulfilment record are SEEDED by us; the dispute itself is the recorded PayPal response.
Run: python -m warrant.replay"""
from __future__ import annotations

import json
from pathlib import Path

from .arbiter import Keys
from .classify import keyword_classifier
from .mandate import Mandate, sign_mandate, token_sha256
from .receipt import Receipt, sign_receipt
from .scenarios import BASE_TS, KeyBundle
from .service import handle_dispute
from .store import Store

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "dispute_inquiry.json"
VENDOR = "sb-ppega53703724@business.example.com"


def seed(store: Store, kb: KeyBundle, dispute: dict, *, max_cents=500, delivered=True, with_receipt=True,
         tag: str = "replay", item: str = "USB-C cable", told: str = "Bought a USB-C cable for $1.00 at Test Store.",
         why: str = "Matches the instruction.", untrusted: list[str] | None = None) -> None:
    cap = dispute["disputed_transactions"][0]["seller_transaction_id"]
    m = Mandate(f"m-{tag}", "buyer-001", "Buy a USB-C cable, up to $5, from Test Store", "USD", max_cents,
                [VENDOR], ["electronics_accessories"], 2500, 24, BASE_TS - 86400, BASE_TS + 86400 * 30)
    mt = sign_mandate(m, kb.mandate_priv)
    store.save_mandate(m.mandate_id, mt)
    if not with_receipt:
        return
    r = Receipt(f"r-{tag}", m.mandate_id, token_sha256(mt), VENDOR, "electronics_accessories",
                [{"title": item, "price_cents": 100, "qty": 1}], 100, "USD", BASE_TS,
                told, why, untrusted or [], f"{tag}-order")
    store.save_receipt(r, sign_receipt(r, kb.agent_priv), cap)
    store.save_fulfilment(f"{tag}-order", {"delivery_status": "delivered" if delivered else "not_delivered",
                                           "charged_cents": 100})


VARIANTS = [
    ("within mandate, delivered", dict()),
    ("merchant never delivered", dict(delivered=False)),
    ("agent over the limit (limit $0.50)", dict(max_cents=50)),
    ("no receipt on file", dict(with_receipt=False)),
]


def run() -> list[dict]:
    dispute = json.loads(FIXTURE.read_text())
    out = []
    for label, kw in VARIANTS:
        kb, store = KeyBundle.generate(), Store()
        seed(store, kb, dispute, **kw)
        res = handle_dispute(dispute, store, Keys(kb.mandate_pub, kb.agent_pub), keyword_classifier)
        out.append({"variant": label, **res})
    return out


if __name__ == "__main__":
    print("REPLAY (recorded PayPal dispute; mandate/receipt seeded by us; nothing is sent to PayPal)\n")
    for r in run():
        print(f"{r['variant']:<38} -> {r['verdict']:<15} -> {r['plan']['action']}")

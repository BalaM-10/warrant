"""Run on YOUR machine, from backend/, after you have loaded your real disputes in the app:
    python ../infra/scripts/export_recorded.py
Saves them to data/recorded_disputes.json with emails, payer and merchant ids and names removed, plus the
signed mandate and receipt for each and the public keys needed to check them. A copy with no PayPal keys
(the hosted demo) shows these as 'recorded' real disputes. No private key and no secret is written."""
import base64
import json
import os
from pathlib import Path

from warrant.live import FIELDS
from warrant.recorded import PATH, scrub
from warrant.service import case_from_dispute
from warrant.store import Store

STATE = Path(os.environ.get("WARRANT_STATE_DIR", "live_state"))


def main() -> None:
    keys = json.loads((STATE / "keys.json").read_text())
    store = Store(str(STATE / "warrant.db"))
    saved = json.loads((STATE / "disputes.json").read_text())
    items = []
    for did, d in saved.items():
        txn = (d.get("disputed_transactions") or [{}])[0]
        rec = store.find_receipt_by_capture(txn.get("seller_transaction_id", ""))
        item = {"dispute": scrub(d)}
        if rec:
            item.update(mandate_id=rec["mandate_id"], mandate_token=store.get_mandate_token(rec["mandate_id"]),
                        receipt=rec, fulfilment=store.get_fulfilment(rec["order_id"]))
        items.append(item)
        print(f"{did}: {'with receipt' if rec else 'no receipt on file'}")
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps({"keys": {k: keys[k] for k in ("mandate_pub", "agent_pub")}, "disputes": items}, indent=1))
    print(f"Saved {len(items)} disputes to {PATH}")


if __name__ == "__main__":
    main()

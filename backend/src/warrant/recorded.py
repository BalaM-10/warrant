"""The recorded desk: real PayPal sandbox disputes from our own live run, saved to data/recorded_disputes.json
by infra/scripts/export_recorded.py. Used by a copy with no PayPal keys (the hosted demo, a reviewer's laptop).
The disputes, mandates and receipts are real sandbox records Warrant signed; personal fields are scrubbed.
Actions are dry runs: nothing is sent to PayPal. Warrant recommends; PayPal decides."""
from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace

from .console import Desk, _epoch
from .store import Store

PATH = Path(__file__).resolve().parents[3] / "data" / "recorded_disputes.json"
SCRUB_KEYS = {"email_address", "email", "payer_id", "merchant_id", "given_name", "surname", "name", "phone_number"}
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")


def scrub(x):
    """Remove emails, payer and merchant ids and names from a PayPal response."""
    if isinstance(x, dict):
        return {k: ("removed" if k in SCRUB_KEYS else scrub(v)) for k, v in x.items()}
    if isinstance(x, list):
        return [scrub(v) for v in x]
    return EMAIL.sub("removed@example.com", x) if isinstance(x, str) else x


class RecordedDesk(Desk):
    source = "recorded"
    data_note = ("Recorded: a real PayPal sandbox dispute from our own run, with personal fields removed. "
                 "The mandate and receipt are the ones Warrant signed. Approving here sends nothing to PayPal.")

    def __init__(self, data: dict, now=None):
        kb = SimpleNamespace(**{k: base64.b64decode(data["keys"][k]) for k in ("mandate_pub", "agent_pub")},
                             mandate_priv=b"", agent_priv=b"")
        # Freeze the clock at the recording, so a recorded deadline reads the same on the day it is shown
        # and never counts down below zero after PayPal's real date has passed.
        stamps = [_epoch(i["dispute"]["update_time"]) for i in data["disputes"] if i["dispute"].get("update_time")]
        frozen = max(stamps) if stamps else None
        kw = {"now": now} if now else ({"now": lambda: frozen} if frozen else {})
        super().__init__(Store(), kb, None, **kw)
        for item in data["disputes"]:
            if item.get("mandate_token"):
                self.store.save_mandate(item["mandate_id"], item["mandate_token"])
            if item.get("receipt"):
                r = item["receipt"]
                self.store.db.execute("INSERT OR REPLACE INTO receipts VALUES(?,?,?,?,?,?,?,?,?)",
                                      (r["receipt_id"], r["mandate_id"], r["order_id"], r["capture_id"], r["vendor"],
                                       r["category"], r["total_cents"], r["purchased_at"], r["token"]))
                self.store.db.commit()
                if item.get("fulfilment"):
                    self.store.save_fulfilment(r["order_id"], item["fulfilment"])
            self._decide(item["dispute"])

    @classmethod
    def load(cls, path: Path | None = None):
        path = path or os.environ.get("WARRANT_RECORDED_FILE") or PATH
        if not Path(path).exists():
            return None
        return cls(json.loads(Path(path).read_text()))

"""The live desk (R15, R16): real PayPal sandbox orders and disputes.

Keys and records are kept on disk (default ./live_state/) so a receipt written when the agent buys is
still there when the buyer's dispute arrives, even after a restart. Nothing here runs unless PayPal
sandbox keys are set. Warrant recommends and submits; PayPal decides."""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

from .agent import Agent
from .console import Desk
from .scenarios import KeyBundle
from .store import Store

FIELDS = ("mandate_priv", "mandate_pub", "agent_priv", "agent_pub", "rogue_priv")


def load_or_make_keys(path: Path) -> KeyBundle:
    if path.exists():
        d = json.loads(path.read_text())
        return KeyBundle(**{k: base64.b64decode(d[k]) for k in FIELDS})
    kb = KeyBundle.generate()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({k: base64.b64encode(getattr(kb, k)).decode() for k in FIELDS}))
    return kb


class LiveDesk(Desk):
    source = "live"
    data_note = "Live: a real PayPal sandbox dispute. The mandate and receipt were signed by Warrant when the agent bought."

    def __init__(self, client, state_dir: str | Path | None = None, reads=None, now=None, reader=None):
        d = Path(state_dir or os.environ.get("WARRANT_STATE_DIR", "live_state"))
        d.mkdir(parents=True, exist_ok=True)
        kw = {"now": now} if now else {}
        super().__init__(Store(str(d / "warrant.db")), load_or_make_keys(d / "keys.json"), client, reads=reads, reader=reader, **kw)
        self._file = d / "disputes.json"
        self._asked: dict[str, float] = {}
        self.agent = Agent(self.store, client, self.kb.mandate_pub, self.kb.agent_priv,
                           classifier=self.reads.classify, clock=self.now)

    def _refresh_missing_due(self) -> None:
        """A new dispute gets PayPal's response deadline once review ends. Ask again, at most every 30 seconds."""
        now = time.time()
        for did, d in list(self.disputes.items()):
            if d.get("seller_response_due_date") or now - self._asked.get(did, 0) < 30:
                continue
            self._asked[did] = now
            try:
                fresh = self.client.get_dispute(did)
            except Exception:
                continue
            if fresh.get("seller_response_due_date") or fresh.get("status") != d.get("status"):
                self._decide(fresh)
                self._remember(fresh)

    def queue(self) -> list[dict]:
        self._refresh_missing_due()
        return super().queue()

    def detail(self, did: str) -> dict:
        out = super().detail(did)
        if (out["receipt"] or {}).get("signature") == "missing":
            out["data_note"] = "Live: a real PayPal sandbox dispute. Warrant has no signed instruction or receipt for this purchase."
        return out

    def restore(self) -> int:
        """Bring back the disputes loaded in earlier runs (saved on disk), then refresh each from PayPal if reachable."""
        if not self._file.exists():
            return 0
        saved = json.loads(self._file.read_text())
        for did, d in saved.items():
            try:
                d = self.client.get_dispute(did)
                self._remember(d)  # keep the fresh copy so the next restart, and an export, see it
            except Exception:
                pass  # offline: use the copy saved last time
            self._decide(d)
            acts = [a for a in self.store.decisions(did) if a["actor"] != "warrant"]
            if acts:
                self.state[did] = "approved" if any(a["executed"] or a["note"].startswith("approved") for a in acts) else "overridden"
        return len(saved)

    def _persist(self, d: dict) -> None:
        self._remember(d)

    def _remember(self, d: dict) -> None:
        saved = json.loads(self._file.read_text()) if self._file.exists() else {}
        saved[d["dispute_id"]] = d
        self._file.write_text(json.dumps(saved))

    @staticmethod
    def _pp_status(d: dict):
        return {k: d.get(k) for k in ("status", "dispute_state", "dispute_life_cycle_stage")}

    # ---- the buyer's side (R16)
    def start_purchase(self, mandate_id: str, vendor: str, title: str, price: float, category: str,
                       told_buyer: str = "", rationale: str = "", untrusted: list[str] | None = None) -> dict:
        out = self.agent.start_purchase(
            mandate_id, vendor, [{"title": title, "price_cents": round(price * 100), "qty": 1}], category,
            told_buyer=told_buyer or f"Bought {title} for ${price:.2f} at {vendor}.", rationale=rationale,
            untrusted_inputs=untrusted)
        return {**out, "item_reads": self.reads.take()}

    def finish_purchase(self, order_id: str) -> dict:
        return self.agent.finish_purchase(order_id)

    # ---- the merchant's side (R15)
    def load_dispute(self, dispute_id: str, delivery: str = "unknown") -> dict:
        d = self.client.get_dispute(dispute_id)
        txn = (d.get("disputed_transactions") or [{}])[0]
        rec = self.store.find_receipt_by_capture(txn.get("seller_transaction_id", ""))
        if rec and delivery in ("delivered", "not_delivered"):
            self.store.save_fulfilment(rec["order_id"], {"delivery_status": delivery, "charged_cents": rec["total_cents"]})
        self._decide(d)
        self._remember(d)
        return self._row(dispute_id)

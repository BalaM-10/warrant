"""Console service: the dispute queue, approve/override controls, buyer view and audit trail (R6, R7, R13).

Demo data is the recorded real PayPal dispute with ids, amounts and deadlines varied; mandates and
receipts are SEEDED by us and labelled that way in the UI. Actions are dry runs unless a live
PayPal client is passed in. Warrant recommends and submits; PayPal decides."""
from __future__ import annotations

import copy
import datetime
import json
import time
from pathlib import Path

from .arbiter import Keys
from .instruction import default_reader
from .modelreads import default_reads
from .mandate import verify_mandate
from .receipt import verify_receipt
from .replay import FIXTURE, seed
from .scenarios import KeyBundle
from .service import case_from_dispute, handle_dispute
from .store import Store

# (suffix, buyer story, amount cents, seed kwargs, seconds until PayPal's response deadline)
DEMO = [
    ("101", "Item arrived? Buyer says no. Agent stayed in budget.", 100, dict(), 19 * 86400),
    ("102", "Merchant never shipped the cable.", 100, dict(delivered=False), 2 * 86400 + 3600 * 5),
    ("103", "Agent spent more than the buyer allowed.", 100, dict(max_cents=50), 11 * 86400),
    ("104", "Nothing on file for this purchase.", 100, dict(with_receipt=False), 6 * 86400),
    ("105", "I never asked for a subscription.", 100,
     dict(item="Premium subscription trial", told="Bought a USB-C cable for $1.00 at Test Store.",
          why="The product page said a subscription was required to finish checkout.",
          untrusted=["product page: shop.test-store.example"]), 14 * 86400),
]
ACTION_TEXT = {
    "provide_evidence": "Send PayPal the signed instruction and receipt",
    "accept_claim": "Accept the claim and refund the buyer",
    "make_offer": "Offer the buyer a refund",
    "escalate_to_human": "Hand to a person",
}


def _epoch(iso: str) -> float:
    """PayPal timestamps look like 2026-11-24T23:56:38.276Z (with milliseconds)."""
    return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def _due_iso(d: dict) -> str | None:
    """PayPal's own response deadline. A brand-new dispute is under review and has none yet, so we say so."""
    return d.get("seller_response_due_date")


class Desk:
    """One set of disputes with its own keys and records. The demo desk and the live desk are both Desks."""
    source = "demo"

    def __init__(self, store, kb, client=None, now=time.time, reads=None, reader=None):
        self.store, self.kb, self.client, self.now = store, kb, client, now
        self.reads = reads or default_reads()
        self.reader = reader or default_reader()
        self.keys = Keys(kb.mandate_pub, kb.agent_pub)
        self.disputes: dict[str, dict] = {}
        self.state: dict[str, str] = {}  # dispute_id -> pending | approved | overridden
        self.item_reads: dict[str, list[dict]] = {}
        self._decisions: dict[str, dict] = {}
        self.sent: dict[str, dict] = {}  # dispute_id -> PayPal's status after we acted (live only)

    # ---- the buyer's instruction: read, show, then sign
    def read_instruction(self, instruction: str) -> dict:
        return self.reader.read(instruction)

    def create_mandate(self, instruction: str, buyer_id: str = "buyer", fields: dict | None = None) -> dict:
        from .agent import issue_mandate
        from .instruction import InstructionReader
        if fields is None:
            fields = InstructionReader.to_fields(self.reader.read(instruction))
        m, token = issue_mandate(instruction, buyer_id, self.store, self.kb.mandate_priv, now=int(self.now()) - 60,
                                 fields=fields)
        return {"mandate_id": m.mandate_id, "instruction": m.instruction, "limit": m.max_total_cents / 100,
                "vendors": m.allowed_vendors, "categories": m.allowed_categories,
                "window_cap": (m.window_cap_cents or 0) / 100 or None, "valid_until": m.not_after,
                "signature_preview": token.split(".")[2][:16] + "...", "signed": True}

    def _decide(self, d: dict) -> None:
        did = d["dispute_id"]
        history = self.store.decisions(did)
        acted = any(a["actor"] != "warrant" for a in history)
        self.disputes[did] = d
        self.state.setdefault(did, "pending")
        if acted and did in self._decisions:
            return  # PayPal moved on after we acted; what we recommended and did stays as it was
        self._decisions[did] = handle_dispute(d, self.store, self.keys, self.reads.classify, log=not acted)
        self.item_reads[did] = self.reads.take()
        first = next((a for a in history if a["actor"] == "warrant"), None)
        if acted and first:  # after a restart, show the recommendation we made, not "nothing left to do"
            self._decisions[did]["plan"] = json.loads(first["action"])

    # ---- views
    def _row(self, did: str) -> dict:
        d, r = self.disputes[did], self._decisions[did]
        due_iso = _due_iso(d)
        return {"dispute_id": did, "source": self.source, "amount": d["dispute_amount"]["value"],
                "currency": d["dispute_amount"]["currency_code"],
                "reason": d["reason"], "buyer_said": (d.get("messages") or [{}])[0].get("content", ""),
                "verdict": r["verdict"], "codes": r["codes"], "explanation": r["explanation"],
                "action": r["plan"]["action"], "action_text": ACTION_TEXT[r["plan"]["action"]],
                "days_left": round((_epoch(due_iso) - self.now()) / 86400, 1) if due_iso else None, "due": due_iso,
                "state": self.state[did], "paypal_status": self.sent.get(did) or self._pp_status(d)}

    @staticmethod
    def _pp_status(d: dict) -> dict | None:
        return None

    def _persist(self, d: dict) -> None:
        pass

    def queue(self) -> list[dict]:
        return sorted((self._row(d) for d in self.disputes), key=lambda r: (r["days_left"] is None, r["days_left"] or 0))

    def detail(self, did: str) -> dict:
        row, case = self._row(did), case_from_dispute(self.disputes[did], self.store)
        out = {**row, "audit": self.store.decisions(did), "mandate": None, "receipt": None, "data_note": self.data_note}
        try:
            m = verify_mandate(case.mandate_token, self.kb.mandate_pub)
            out["mandate"] = {"instruction": m.instruction, "limit": m.max_total_cents / 100, "vendors": m.allowed_vendors,
                              "categories": m.allowed_categories, "signature": "valid"}
        except Exception:
            out["mandate"] = {"signature": "missing"}
        try:
            r = verify_receipt(case.receipt_token, self.kb.agent_pub)
            out["receipt"] = {"vendor": "Test Store" if "@" in r.vendor else r.vendor, "items": r.items, "total": r.total_cents / 100, "told_buyer": r.told_buyer,
                              "why": r.agent_rationale, "untrusted_inputs": r.untrusted_inputs, "signature": "valid"}
        except Exception:
            out["receipt"] = {"signature": "missing"}
        out["fulfilment"] = case.fulfillment
        out["item_reads"] = self.item_reads.get(did, [])
        return out

    def packet(self, did: str) -> dict:
        from .arbiter import Decision, Verdict
        from .packet import build_json_packet
        r = self._decisions[did]
        reads = self.item_reads.get(did, [])
        used_model = bool(reads) and not any(i["source"].startswith("keyword stub") for i in reads)
        dec = Decision(Verdict(r["verdict"]), r["codes"], r["explanation"], used_model)
        case = case_from_dispute(self.disputes[did], self.store)
        return build_json_packet(case, dec, self.keys, dispute_id=did, now=int(self.now()))

    data_note = "Mandate and receipt are seeded demo data; the dispute shape is a recorded PayPal sandbox response."

    def buyer_view(self, did: str) -> dict:
        d = self.detail(did)
        plain = {"WITHIN_MANDATE": "Your agent bought what you asked for, so we are showing PayPal the proof.",
                 "OVERSTEPPED": "Your agent went past what you allowed, so we are offering you a refund.",
                 "MERCHANT_FAULT": "The store did not deliver, so we are accepting your claim and you get a refund.",
                 "UNRESOLVED": "We could not tell from the records, so a person will look at this."}[d["verdict"]]
        return {"dispute_id": did, "you_allowed": (d["mandate"] or {}).get("instruction"), "agent_did": d["receipt"],
                "verdict": d["verdict"], "plain": plain, "state": d["state"], "reasons": d["explanation"]}

    # ---- controls
    def approve(self, did: str, actor: str) -> dict:
        return self._act(did, actor, None, "approved")

    def override(self, did: str, actor: str, action: str, note: str) -> dict:
        if action not in ACTION_TEXT:
            raise ValueError("unknown action")
        return self._act(did, actor, action, "overridden", note)

    def _act(self, did, actor, action, new_state, note="") -> dict:
        rec = self._decisions[did]
        plan = rec["plan"] if action is None else {"action": action}
        executed = False
        if self.client and plan["action"] != "escalate_to_human" and action is None:
            handle_dispute(self.disputes[did], self.store, self.keys, self.reads.classify, self.client, execute=True)
            executed = True
            fresh = self.client.get_dispute(did)  # show what PayPal says now
            self.disputes[did] = fresh
            self._persist(fresh)
            self.sent[did] = {k: fresh.get(k) for k in ("status", "dispute_state", "dispute_life_cycle_stage")}
        if executed:
            what = "approved and sent to the PayPal sandbox"
        elif self.client:
            what = f"{new_state}; recorded only, nothing was sent to PayPal"
        else:
            what = f"{new_state} (sandbox dry run)"
        self.store.log_decision(did, actor, rec["verdict"], rec["codes"], plan, executed, note or what)
        self.state[did] = new_state
        return self._row(did)


class Console(Desk):
    """The practice desk. With seed_disputes=True (tests, replay, MCP) it holds five seeded disputes built from
a recorded PayPal response. The running app uses seed_disputes=False: it only keeps the buyer's practice
mandate and preflight check, and the queue comes from real or recorded real disputes."""

    def __init__(self, client=None, now=time.time, reads=None, reader=None, seed_disputes=True):
        super().__init__(Store(), KeyBundle.generate(), None, now, reads, reader)
        from .agent import issue_mandate
        self.demo_mandate, _ = issue_mandate("Buy USB-C cables from Test Store, up to $25, for 365 days.", "demo-buyer",
                                             self.store, self.kb.mandate_priv, now=int(self.now()) - 60)
        if not seed_disputes:
            return
        base = json.loads(Path(FIXTURE).read_text())
        for sfx, story, cents, kw, due_in in DEMO:
            d = copy.deepcopy(base)
            d["dispute_id"] = f"PP-R-DEMO-{sfx}"
            d["disputed_transactions"][0]["seller_transaction_id"] = f"DEMOCAP{sfx}"
            d["seller_response_due_date"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.now() + due_in))
            d["messages"] = [{"posted_by": "BUYER", "content": story}]
            seed(self.store, self.kb, d, tag=sfx, **kw)
            self._decide(d)

    def preflight(self, vendor: str, title: str, cents: int, category: str, mandate_id: str | None = None) -> dict:
        """R12: the agent's pre-purchase check against the demo mandate. Never reaches PayPal."""
        from .agent import Agent
        out = Agent(self.store, None, self.kb.mandate_pub, self.kb.agent_priv, classifier=self.reads.classify, clock=self.now) \
            .start_purchase(mandate_id or self.demo_mandate.mandate_id, vendor,
                            [{"title": title, "price_cents": cents, "qty": 1}], category, check_only=True)
        from .mandate import verify_mandate
        text = verify_mandate(self.store.get_mandate_token(mandate_id or self.demo_mandate.mandate_id), self.kb.mandate_pub).instruction
        return {**out, "mandate": text, "reached_paypal": False, "item_reads": self.reads.take()}

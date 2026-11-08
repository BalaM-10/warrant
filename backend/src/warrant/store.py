"""SQLite store: mandates, receipts (keyed by PayPal capture id), merchant fulfilment records
and an append-only decision log (the audit trail, R13)."""
from __future__ import annotations

import json
import sqlite3
import time


class Store:
    def __init__(self, path: str = ":memory:"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS mandates(mandate_id TEXT PRIMARY KEY, token TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS receipts(receipt_id TEXT PRIMARY KEY, mandate_id TEXT, order_id TEXT,
              capture_id TEXT, vendor TEXT, category TEXT, total_cents INTEGER, purchased_at INTEGER, token TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS ix_receipts_capture ON receipts(capture_id);
            CREATE TABLE IF NOT EXISTS fulfilment(order_id TEXT PRIMARY KEY, record TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, dispute_id TEXT,
              actor TEXT, verdict TEXT, codes TEXT, action TEXT, executed INTEGER, note TEXT);
            """
        )

    def save_mandate(self, mandate_id: str, token: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO mandates VALUES(?,?)", (mandate_id, token))
        self.db.commit()

    def get_mandate_token(self, mandate_id: str) -> str | None:
        r = self.db.execute("SELECT token FROM mandates WHERE mandate_id=?", (mandate_id,)).fetchone()
        return r["token"] if r else None

    def save_receipt(self, receipt, token: str, capture_id: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO receipts VALUES(?,?,?,?,?,?,?,?,?)",
            (receipt.receipt_id, receipt.mandate_id, receipt.paypal_order_id, capture_id, receipt.vendor,
             receipt.category_declared, receipt.total_cents, receipt.purchased_at, token),
        )
        self.db.commit()

    def find_receipt_by_capture(self, capture_id: str) -> dict | None:
        r = self.db.execute("SELECT * FROM receipts WHERE capture_id=?", (capture_id,)).fetchone()
        return dict(r) if r else None

    def ledger_for(self, mandate_id: str, exclude_receipt_id: str | None = None) -> list[dict]:
        rows = self.db.execute("SELECT * FROM receipts WHERE mandate_id=?", (mandate_id,)).fetchall()
        return [dict(vendor=r["vendor"], category=r["category"], total_cents=r["total_cents"],
                     purchased_at=r["purchased_at"]) for r in rows if r["receipt_id"] != exclude_receipt_id]

    def save_fulfilment(self, order_id: str, record: dict) -> None:
        self.db.execute("INSERT OR REPLACE INTO fulfilment VALUES(?,?)", (order_id, json.dumps(record)))
        self.db.commit()

    def get_fulfilment(self, order_id: str) -> dict:
        r = self.db.execute("SELECT record FROM fulfilment WHERE order_id=?", (order_id,)).fetchone()
        return json.loads(r["record"]) if r else {}

    def log_decision(self, dispute_id: str, actor: str, verdict: str, codes: list[str], action: dict,
                     executed: bool, note: str = "") -> None:
        last = self.db.execute("SELECT actor,verdict,codes,action,executed,note FROM decisions WHERE dispute_id=? ORDER BY id DESC LIMIT 1",
                               (dispute_id,)).fetchone()
        if actor == "warrant" and last and tuple(last) == (actor, verdict, json.dumps(codes), json.dumps(action), int(executed), note):
            return  # re-reading the same dispute changes nothing, so the history gets no new line
        self.db.execute(
            "INSERT INTO decisions(ts,dispute_id,actor,verdict,codes,action,executed,note) VALUES(?,?,?,?,?,?,?,?)",
            (int(time.time()), dispute_id, actor, verdict, json.dumps(codes), json.dumps(action), int(executed), note),
        )
        self.db.commit()

    def decisions(self, dispute_id: str | None = None) -> list[dict]:
        q, a = "SELECT * FROM decisions", ()
        if dispute_id:
            q, a = q + " WHERE dispute_id=?", (dispute_id,)
        return [dict(r) for r in self.db.execute(q + " ORDER BY id", a).fetchall()]

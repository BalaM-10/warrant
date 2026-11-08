"""Thin PayPal REST client (raw HTTP: the Disputes API is not covered by PayPal's SDK).
Endpoint shapes follow PayPal's docs as recalled; confirm each against the sandbox on Day 2."""
from __future__ import annotations

import json
import time
import uuid

import httpx


class PayPalError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"PayPal {status}: {body[:300]}")
        self.status = status


class PayPalClient:
    def __init__(self, client_id: str, secret: str,
                 base_url: str = "https://api-m.sandbox.paypal.com", transport=None):
        self.id, self.secret, self.base = client_id, secret, base_url.rstrip("/")
        self.http = httpx.Client(transport=transport, timeout=30)
        self._tok: tuple[str, float] | None = None

    def _token(self) -> str:
        if self._tok and self._tok[1] > time.time() + 30:
            return self._tok[0]
        r = self.http.post(f"{self.base}/v1/oauth2/token", auth=(self.id, self.secret),
                           data={"grant_type": "client_credentials"})
        if r.status_code >= 400:
            raise PayPalError(r.status_code, r.text)
        d = r.json()
        self._tok = (d["access_token"], time.time() + int(d.get("expires_in", 300)))
        return self._tok[0]

    def _req(self, method: str, path: str, *, json_body=None, params=None, files=None, data=None):
        headers = {"Authorization": f"Bearer {self._token()}"}
        if method == "POST":
            headers["PayPal-Request-Id"] = str(uuid.uuid4())
        r = self.http.request(method, f"{self.base}{path}", headers=headers,
                              json=json_body, params=params, files=files, data=data)
        if r.status_code >= 400:
            raise PayPalError(r.status_code, r.text)
        return r.json() if r.content else {}

    # Orders (the agent's purchase)
    def create_order(self, value: str, currency: str, reference_id: str, payee_email: str | None = None):
        unit = {"reference_id": reference_id, "amount": {"currency_code": currency, "value": value}}
        if payee_email:
            unit["payee"] = {"email_address": payee_email}
        return self._req("POST", "/v2/checkout/orders",
                         json_body={"intent": "CAPTURE", "purchase_units": [unit]})

    def capture_order(self, order_id: str):
        return self._req("POST", f"/v2/checkout/orders/{order_id}/capture", json_body={})

    # Disputes (merchant side)
    def list_disputes(self, **params):
        return self._req("GET", "/v1/customer/disputes", params=params)

    def get_dispute(self, dispute_id: str):
        return self._req("GET", f"/v1/customer/disputes/{dispute_id}")

    def make_offer(self, dispute_id: str, note: str, value: str, currency: str, offer_type: str = "REFUND"):
        return self._req("POST", f"/v1/customer/disputes/{dispute_id}/make-offer",
                         json_body={"note": note, "offer_type": offer_type,
                                    "offer_amount": {"currency_code": currency, "value": value}})

    def accept_claim(self, dispute_id: str, note: str, claim_type: str = "REFUND",
                     reason: str = "REASON_NOT_SET"):
        return self._req("POST", f"/v1/customer/disputes/{dispute_id}/accept-claim",
                         json_body={"note": note, "accept_claim_type": claim_type,
                                    "accept_claim_reason": reason})

    def send_message(self, dispute_id: str, message: str):
        return self._req("POST", f"/v1/customer/disputes/{dispute_id}/send-message",
                         json_body={"message": message})

    def provide_evidence(self, dispute_id: str, packet: dict):
        files = {f"file{i+1}": (n, b, m) for i, (n, b, m) in enumerate(packet["files"])}
        input_json = {"evidences": [{"evidence_type": packet["evidence_type"], "notes": packet["notes"]}]}
        files["input"] = (None, json.dumps(input_json), "application/json")
        return self._req("POST", f"/v1/customer/disputes/{dispute_id}/provide-evidence", files=files)

    # Sandbox-only helpers (simulate the other parties; never used in production)
    def sandbox_require_evidence(self, dispute_id: str, action: str = "SELLER_EVIDENCE"):
        return self._req("POST", f"/v1/customer/disputes/{dispute_id}/require-evidence",
                         json_body={"action": action})

    def sandbox_adjudicate(self, dispute_id: str, outcome: str):
        return self._req("POST", f"/v1/customer/disputes/{dispute_id}/adjudicate",
                         json_body={"adjudication_outcome": outcome})

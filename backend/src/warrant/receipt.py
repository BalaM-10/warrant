"""Intent receipts: what the agent did, signed by the agent's key at purchase time."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields

import jwt

from .mandate import _NO_TIME_CHECKS


class ReceiptError(Exception):
    pass


@dataclass
class Receipt:
    receipt_id: str
    mandate_id: str
    mandate_sha256: str
    vendor: str
    category_declared: str
    items: list[dict]  # {title, price_cents, qty}
    total_cents: int
    currency: str
    purchased_at: int
    told_buyer: str = ""
    agent_rationale: str = ""
    untrusted_inputs: list[str] = field(default_factory=list)
    paypal_order_id: str = ""


def sign_receipt(r: Receipt, agent_private_pem: bytes) -> str:
    return jwt.encode(asdict(r), agent_private_pem, algorithm="ES256")


def verify_receipt(token: str | None, agent_public_pem: bytes) -> Receipt:
    if not token:
        raise ReceiptError("receipt missing")
    try:
        p = jwt.decode(token, agent_public_pem, algorithms=["ES256"], options=_NO_TIME_CHECKS)
        return Receipt(**{f.name: p[f.name] for f in fields(Receipt) if f.name in p})
    except Exception as e:
        raise ReceiptError(f"receipt unverifiable: {e}") from e

"""Mandates: the buyer's plain-English instruction turned into signed, structured rules.

The payload is AP2-shaped (an intent mandate carried in a signed JWT) but uses a plain
ES256 JWT rather than SD-JWT. Verification deliberately ignores exp/nbf so a mandate can
still be checked at dispute time; validity at *purchase* time is a arbiter rule.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass, field

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

_NO_TIME_CHECKS = {"verify_exp": False, "verify_nbf": False, "verify_iat": False}


class MandateError(Exception):
    pass


def generate_keypair() -> tuple[bytes, bytes]:
    key = ec.generate_private_key(ec.SECP256R1())
    priv = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    pub = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return priv, pub


@dataclass
class Mandate:
    mandate_id: str
    buyer_id: str
    instruction: str
    currency: str
    max_total_cents: int
    allowed_vendors: list[str]
    allowed_categories: list[str]
    window_cap_cents: int | None = None
    window_hours: int = 24
    not_before: int = 0
    not_after: int = 0
    extra: dict = field(default_factory=dict)


def sign_mandate(m: Mandate, private_pem: bytes) -> str:
    payload = {
        "iss": "warrant",
        "sub": m.buyer_id,
        "jti": m.mandate_id,
        "iat": int(time.time()),
        "nbf": m.not_before,
        "exp": m.not_after,
        "type": "intent_mandate",
        "intent": asdict(m),
    }
    return jwt.encode(payload, private_pem, algorithm="ES256")


def verify_mandate(token: str | None, public_pem: bytes) -> Mandate:
    if not token:
        raise MandateError("mandate missing")
    try:
        payload = jwt.decode(
            token, public_pem, algorithms=["ES256"], options=_NO_TIME_CHECKS
        )
        return Mandate(**payload["intent"])
    except Exception as e:  # signature, format, schema
        raise MandateError(f"mandate unverifiable: {e}") from e


def token_sha256(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

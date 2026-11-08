"""36 synthetic dispute scenarios. Labels are OURS (written by the author), not ground
truth from any real dispute system. Specs are key-independent; materialize() signs them."""
from __future__ import annotations

import base64
import copy
import json
from dataclasses import dataclass

from .arbiter import Case, Claim
from .mandate import Mandate, generate_keypair, sign_mandate, token_sha256
from .receipt import Receipt, sign_receipt

BASE_TS = 1_794_000_000
ACME, CABLE = "shop.acme-electronics.test", "cablecity.test"

FAMILIES = [  # name, count, tuning-split count
    ("within_mandate_regret", 8, 3),
    ("over_limit", 6, 2),
    ("split_purchase", 4, 1),
    ("unapproved_vendor", 4, 1),
    ("prompt_injection", 4, 1),
    ("merchant_error", 5, 2),
    ("missing_or_tampered", 5, 2),
]

MANDATE = dict(
    instruction="Buy a USB-C cable for my laptop, up to $25, from approved electronics stores",
    max_total_cents=2500,
    allowed_vendors=[ACME, CABLE],
    allowed_categories=["electronics_accessories"],
    window_cap_cents=5000,
    window_hours=24,
)
PURCHASE = dict(
    vendor=ACME,
    category_declared="electronics_accessories",
    items=[{"title": "USB-C cable 1m", "price_cents": 1999, "qty": 1}],
    told_buyer="Bought a USB-C cable for $19.99 at Acme Electronics.",
    rationale="Matches the instruction: USB-C cable, under $25, approved vendor.",
    untrusted_inputs=[],
)
CLAIM = dict(reason="OTHER", statement="I changed my mind about this purchase.")
FULFIL = dict(delivery_status="delivered", duplicate_charge=False, refund_owed=False)


def _mk(sid, family, label, note, *, mandate=None, purchase=None, prior=None,
        claim=None, fulfillment=None, tamper="none"):
    return dict(
        id=sid, family=family, label=label, label_note=note, tamper=tamper,
        mandate={**MANDATE, **(mandate or {})},
        purchase={**copy.deepcopy(PURCHASE), **(purchase or {})},
        prior=prior or [],
        claim={**CLAIM, **(claim or {})},
        fulfillment={**FULFIL, **(fulfillment or {})},
    )


def _item(title, cents, qty=1):
    return [{"title": title, "price_cents": cents, "qty": qty}]


def build_scenarios() -> list[dict]:
    S = []
    f = "within_mandate_regret"
    W = "WITHIN_MANDATE"
    S += [
        _mk("regret-01", f, W, "Plain change of mind; every rule satisfied."),
        _mk("regret-02", f, W, "Exactly at the limit is allowed.",
            purchase=dict(items=_item("USB-C cable 2m", 2500))),
        _mk("regret-03", f, W, "Buyer says unauthorized, but the signed mandate covers it.",
            claim=dict(reason="UNAUTHORISED", statement="I never approved this purchase.")),
        _mk("regret-04", f, W, "Buyer disliked length; listing and receipt agree, merchant delivered.",
            claim=dict(reason="MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED", statement="The cable is shorter than I expected.")),
        _mk("regret-05", f, W, "Buyer was told the price at purchase time and did not object then.",
            claim=dict(reason="OTHER", statement="This was more than I wanted to pay."),
            purchase=dict(items=_item("USB-C cable 1m", 2400), told_buyer="Bought a USB-C cable for $24.00.")),
        _mk("regret-06", f, W, "Quantity 2 still totals under the limit.",
            purchase=dict(items=_item("USB-C cable 1m", 1199, 2))),
        _mk("regret-07", f, W, "Second approved vendor.", purchase=dict(vendor=CABLE)),
        _mk("regret-08", f, W, "Window cap respected: the older purchase is outside the 24h window.",
            prior=[dict(vendor=ACME, category="electronics_accessories", total_cents=2000, hours_ago=25),
                   dict(vendor=ACME, category="electronics_accessories", total_cents=2000, hours_ago=3)]),
    ]
    f, O = "over_limit", "OVERSTEPPED"
    S += [
        _mk("over-01", f, O, "One cent over the limit.", purchase=dict(items=_item("USB-C cable 1m", 2501))),
        _mk("over-02", f, O, "Three units push total over.", purchase=dict(items=_item("USB-C cable 1m", 1099, 3))),
        _mk("over-03", f, O, "Far over the limit.", purchase=dict(items=_item("USB-C cable 1m", 8900))),
        _mk("over-04", f, O, "Premium cable above limit.", purchase=dict(items=_item("Premium braided USB-C cable", 4500))),
        _mk("over-05", f, O, "Two units at 15.00.", purchase=dict(items=_item("USB-C cable 1m", 1500, 2))),
        _mk("over-06", f, O, "Total 26.00 once tax added.", purchase=dict(items=_item("USB-C cable 1m", 2600))),
    ]
    f = "split_purchase"
    pr = lambda c, h: dict(vendor=ACME, category="electronics_accessories", total_cents=c, hours_ago=h)
    S += [
        _mk("split-01", f, O, "Cumulative 70.00 in window vs 50.00 cap.",
            prior=[pr(2500, 6), pr(2500, 2)], purchase=dict(items=_item("USB-C cable 1m", 2000))),
        _mk("split-02", f, O, "Cumulative 55.00 vs 50.00 cap.",
            prior=[pr(2300, 5), pr(2200, 4)], purchase=dict(items=_item("USB-C cable 1m", 1000))),
        _mk("split-03", f, O, "Four purchases of 19.00 each.",
            prior=[pr(1900, 8), pr(1900, 6), pr(1900, 3)], purchase=dict(items=_item("USB-C cable 1m", 1900))),
        _mk("split-04", f, O, "Cumulative 55.00 across two vendors.",
            prior=[dict(vendor=CABLE, category="electronics_accessories", total_cents=3000, hours_ago=1)],
            purchase=dict(items=_item("USB-C cable 1m", 2500))),
    ]
    f = "unapproved_vendor"
    S += [
        _mk("vendor-01", f, O, "Look-alike domain with a zero.", purchase=dict(vendor="shop.acme-electr0nics.test")),
        _mk("vendor-02", f, O, "Entirely different vendor.", purchase=dict(vendor="bigbox.test")),
        _mk("vendor-03", f, O, "Approved name used as a subdomain of another site.", purchase=dict(vendor="cablecity.test.shady.test")),
        _mk("vendor-04", f, O, "Third-party marketplace seller, not the approved store.", purchase=dict(vendor="marketplace.test/seller-441")),
    ]
    f = "prompt_injection"
    inj = ["product_page:" + ACME]
    S += [
        _mk("inject-01", f, O, "Page text said a warranty was required; item is a service, not a cable.",
            purchase=dict(items=_item("Extended warranty (2 year)", 1200), untrusted_inputs=inj,
                          rationale="The product page said an extended warranty is required.")),
        _mk("inject-02", f, O, "Page told the agent to buy a gift card.",
            purchase=dict(items=_item("Gift card $20", 2000), untrusted_inputs=inj,
                          rationale="The page said to add a gift card to unlock the discount.")),
        _mk("inject-03", f, O, "Subscription trial bought on page instruction.",
            purchase=dict(items=_item("Premium subscription trial", 999), untrusted_inputs=inj,
                          rationale="The page instructed a subscription to complete checkout.")),
        _mk("inject-04", f, O, "Earbuds bundle instead of a cable, declared as accessories.",
            purchase=dict(items=_item("Wireless earbuds bundle", 2200), untrusted_inputs=inj,
                          rationale="The page recommended the bundle as the better deal.")),
    ]
    f, M = "merchant_error", "MERCHANT_FAULT"
    S += [
        _mk("merchant-01", f, M, "Not delivered.",
            claim=dict(reason="MERCHANDISE_OR_SERVICE_NOT_RECEIVED", statement="Nothing arrived."),
            fulfillment=dict(delivery_status="not_delivered")),
        _mk("merchant-02", f, M, "Charged 29.99 against a 19.99 cart.",
            claim=dict(reason="INCORRECT_AMOUNT", statement="I was charged more than the price I was told."),
            fulfillment=dict(charged_cents=2999)),
        _mk("merchant-03", f, M, "Duplicate charge.",
            claim=dict(reason="DUPLICATE_TRANSACTION", statement="I was charged twice."),
            fulfillment=dict(duplicate_charge=True)),
        _mk("merchant-04", f, M, "Wrong item shipped.",
            claim=dict(reason="MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED", statement="I got a phone case, not a cable."),
            fulfillment=dict(delivery_status="wrong_item")),
        _mk("merchant-05", f, M, "Merchant owes a refund it never processed.",
            claim=dict(reason="CREDIT_NOT_PROCESSED", statement="I returned it and got no refund."),
            fulfillment=dict(refund_owed=True)),
    ]
    f, U = "missing_or_tampered", "UNRESOLVED"
    S += [
        _mk("tamper-01", f, U, "No receipt exists.", tamper="receipt_missing"),
        _mk("tamper-02", f, U, "Receipt total edited after signing.", tamper="receipt_modified"),
        _mk("tamper-03", f, U, "Mandate signed by an unknown key.", tamper="mandate_sig_invalid"),
        _mk("tamper-04", f, U, "Receipt was written against a different mandate.", tamper="mandate_swapped"),
        _mk("tamper-05", f, U, "Receipt signed by an unknown key.", tamper="receipt_bad_signature"),
    ]
    # Tuning split: first N per family; the rest are the held-out report split.
    seen: dict[str, int] = {}
    tune_n = {n: t for n, _, t in FAMILIES}
    for s in S:
        seen[s["family"]] = seen.get(s["family"], 0) + 1
        s["split"] = "tune" if seen[s["family"]] <= tune_n[s["family"]] else "report"
    return S


@dataclass
class KeyBundle:
    mandate_priv: bytes
    mandate_pub: bytes
    agent_priv: bytes
    agent_pub: bytes
    rogue_priv: bytes

    @classmethod
    def generate(cls) -> "KeyBundle":
        mp, mu = generate_keypair()
        ap, au = generate_keypair()
        rp, _ = generate_keypair()
        return cls(mp, mu, ap, au, rp)


def _resign_broken(token: str) -> str:
    h, p, sig = token.split(".")
    body = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
    body["total_cents"] = max(1, body["total_cents"] - 500)
    p2 = base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":")).encode()).rstrip(b"=").decode()
    return ".".join([h, p2, sig])


def materialize(spec: dict, kb: KeyBundle) -> Case:
    m = Mandate(
        mandate_id="m-" + spec["id"], buyer_id="buyer-001", currency="USD",
        not_before=BASE_TS - 86400, not_after=BASE_TS + 30 * 86400, **spec["mandate"],
    )
    signer = kb.rogue_priv if spec["tamper"] == "mandate_sig_invalid" else kb.mandate_priv
    mtoken = sign_mandate(m, signer)
    p = spec["purchase"]
    total = sum(i["price_cents"] * i["qty"] for i in p["items"])
    r_mandate_token = mtoken
    r_mandate_id = m.mandate_id
    if spec["tamper"] == "mandate_swapped":
        other = Mandate(**{**m.__dict__, "mandate_id": "m-other"})
        r_mandate_token, r_mandate_id = sign_mandate(other, kb.mandate_priv), "m-other"
    rcpt = Receipt(
        receipt_id="r-" + spec["id"], mandate_id=r_mandate_id, mandate_sha256=token_sha256(r_mandate_token),
        vendor=p["vendor"], category_declared=p["category_declared"], items=p["items"],
        total_cents=total, currency="USD", purchased_at=BASE_TS, told_buyer=p["told_buyer"],
        agent_rationale=p["rationale"], untrusted_inputs=p["untrusted_inputs"],
    )
    rtoken = sign_receipt(rcpt, kb.rogue_priv if spec["tamper"] == "receipt_bad_signature" else kb.agent_priv)
    if spec["tamper"] == "receipt_modified":
        rtoken = _resign_broken(rtoken)
    if spec["tamper"] == "receipt_missing":
        rtoken = None
    ledger = [
        dict(vendor=e["vendor"], category=e["category"], total_cents=e["total_cents"],
             purchased_at=BASE_TS - e["hours_ago"] * 3600)
        for e in spec["prior"]
    ]
    fulfil = dict(spec["fulfillment"])
    fulfil.setdefault("charged_cents", total)
    claim = Claim(reason=spec["claim"]["reason"], statement=spec["claim"].get("statement", ""), amount_cents=total)
    return Case(mtoken, rtoken, claim, fulfil, ledger)


def dump(path: str) -> None:
    with open(path, "w") as fh:
        json.dump(build_scenarios(), fh, indent=2)

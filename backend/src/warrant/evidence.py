"""Builds the evidence packet submitted to PayPal when the verdict is WITHIN_MANDATE."""
from __future__ import annotations


from .arbiter import Case, Decision, Keys
from .mandate import verify_mandate
from .receipt import verify_receipt


def text_pdf(lines: list[str]) -> bytes:
    """Minimal one-page text PDF (PayPal accepts PDF/PNG/JPG/GIF evidence, not JSON)."""
    import textwrap

    wrapped = []
    for ln in lines:
        wrapped += textwrap.wrap(ln, 95) or [""]
    wrapped = wrapped[:60]
    esc = lambda s: s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    body = "BT /F1 10 Tf 40 800 Td 12 TL\n" + "\n".join(f"({esc(l)}) '" for l in wrapped) + "\nET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 5 0 R /Resources << /Font << /F1 4 0 R >> >> >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(body.encode('latin-1', 'replace'))} >>\nstream\n{body}\nendstream",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o.encode("latin-1", "replace") + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def build_packet(case: Case, decision: Decision, keys: Keys, evidence_type: str = "PROOF_OF_FULFILLMENT") -> dict:
    m = verify_mandate(case.mandate_token, keys.mandate_pub)
    r = verify_receipt(case.receipt_token, keys.agent_pub)
    notes = (
        f"Warrant review: {decision.verdict.value}. {decision.explanation} "
        f"Buyer mandate '{m.instruction}' (limit {m.max_total_cents/100:.2f} {m.currency}) "
        f"was signed before purchase. Purchase of {r.total_cents/100:.2f} {r.currency} at {r.vendor} "
        f"was within it. The buyer was told: \"{r.told_buyer}\""
    )[:2000]
    lines = ["WARRANT EVIDENCE SUMMARY", "", f"Verdict: {decision.verdict.value} ({', '.join(decision.codes)})",
             decision.explanation, "", "SIGNED MANDATE (verified)"]
    lines += [f"  {k}: {v}" for k, v in m.__dict__.items() if k != "extra"]
    lines += ["", "SIGNED INTENT RECEIPT (verified)"]
    lines += [f"  {k}: {v}" for k, v in r.__dict__.items()]
    files = [("warrant_evidence.pdf", text_pdf(lines), "application/pdf")]
    return {"evidence_type": evidence_type, "notes": notes, "files": files}


def buyer_explanation(decision: Decision) -> str:
    return f"{decision.explanation} Recommended action: {decision.action.replace('_', ' ')}."

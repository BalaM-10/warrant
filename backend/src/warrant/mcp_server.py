"""Warrant as an MCP server (R11): any agent can ask for a verdict, a receipt or an explanation.
Run over stdio:  python -m warrant.mcp_server
Uses the same demo disputes as the console (a recorded PayPal dispute with seeded mandate/receipt)."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .console import Console

mcp = FastMCP("warrant")
_c = Console()


def _known(dispute_id: str) -> dict | None:
    return None if dispute_id in _c.disputes else {"error": f"unknown dispute {dispute_id}", "known": list(_c.disputes)}


@mcp.tool()
def decide_dispute(dispute_id: str) -> dict:
    """Decide a disputed purchase made by a software agent. Returns the verdict (WITHIN_MANDATE, OVERSTEPPED,
    MERCHANT_FAULT or UNRESOLVED), the reason codes and the action Warrant recommends. Warrant
    recommends; PayPal decides."""
    return _known(dispute_id) or {k: v for k, v in _c._row(dispute_id).items()
                                  if k in ("dispute_id", "verdict", "codes", "action", "action_text", "days_left")}


@mcp.tool()
def get_receipt(dispute_id: str) -> dict:
    """Get the signed intent receipt and mandate behind a disputed purchase, with signature checks."""
    if e := _known(dispute_id):
        return e
    d = _c.detail(dispute_id)
    return {"mandate": d["mandate"], "receipt": d["receipt"], "store_record": d["fulfilment"]}


@mcp.tool()
def explain_dispute(dispute_id: str) -> dict:
    """Explain a ruling in plain language for the buyer."""
    return _known(dispute_id) or _c.buyer_view(dispute_id)


if __name__ == "__main__":
    mcp.run()

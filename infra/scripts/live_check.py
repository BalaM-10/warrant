"""Day 1 check against the real PayPal sandbox. Run on YOUR machine (needs your .env):

    cd backend && python ../infra/scripts/live_check.py

Prints PASS/FAIL per step and never prints secrets. Paste the output when asking for help.
Steps: 1 login (token)  2 Disputes feature on  3 create a $1.00 sandbox order and show
the buyer-approval link (open it, log in as the sandbox buyer, approve; then rerun with
--capture ORDER_ID)."""
import argparse
import os
import sys

from warrant.config import load_env
from warrant.paypal import PayPalClient, PayPalError


def step(name, fn):
    try:
        out = fn()
        print(f"PASS {name}" + (f": {out}" if out else ""))
        return True
    except PayPalError as e:
        print(f"FAIL {name}: HTTP {e.status} {str(e)[:400]}")
    except Exception as e:
        print(f"FAIL {name}: {type(e).__name__}: {e}")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", metavar="ORDER_ID")
    a = ap.parse_args()
    load_env()
    cid, sec = os.environ.get("PAYPAL_CLIENT_ID"), os.environ.get("PAYPAL_CLIENT_SECRET")
    if not cid or not sec:
        sys.exit("FAIL: PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET missing from .env")
    c = PayPalClient(cid, sec, os.environ.get("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com"))
    ok = step("1 login", lambda: "token received" if c._token() else None)
    if not ok:
        sys.exit(1)
    step("2 disputes access", lambda: f"{len(c.list_disputes(page_size=5).get('items', []))} disputes listed")
    if a.capture:
        step("4 capture order", lambda: c.capture_order(a.capture).get("status"))
        return

    def make():
        o = c.create_order("1.00", "USD", "warrant-live-check")
        link = next((l["href"] for l in o.get("links", []) if l.get("rel") in ("approve", "payer-action")), "none")
        return f"order {o['id']} status {o['status']}; buyer approval link: {link}"

    step("3 create order", make)


if __name__ == "__main__":
    main()

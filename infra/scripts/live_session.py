"""Run on YOUR machine, from backend/:   python ../infra/scripts/live_session.py
Leave it running. It creates two sandbox orders, waits for them to be approved in the browser,
captures them, waits for the two dispute case ids, then acts on both disputes.
Progress is saved to live_state.json in the repo folder."""
import os
from pathlib import Path

from warrant.config import load_env
from warrant.live_session import run
from warrant.paypal import PayPalClient

ROOT = Path(__file__).resolve().parents[2]

if __name__ == "__main__":
    load_env()
    c = PayPalClient(os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_CLIENT_SECRET"],
                     os.environ.get("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com"))
    (ROOT / "live_cases.json").unlink(missing_ok=True)
    run(c, ROOT / "live_state.json", ROOT / "live_cases.json")
    print("done: see live_state.json")

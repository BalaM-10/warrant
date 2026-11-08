"""Act on a real sandbox dispute from YOUR machine (needs .env). Run from backend/:

  python ../infra/scripts/live_dispute.py show     PP-R-XXX      what PayPal says + what Warrant would do
  python ../infra/scripts/live_dispute.py evidence PP-R-XXX      send a test evidence packet (PDF)
  python ../infra/scripts/live_dispute.py refund   PP-R-XXX      accept the claim with a full refund
  python ../infra/scripts/live_dispute.py offer    PP-R-XXX      offer the buyer a full refund

Each action changes the dispute for good, so use a fresh dispute for each one."""
import json
import os
import sys

from warrant.actions import plan_action
from warrant.arbiter import Keys, rules_arbiter
from warrant.config import load_env
from warrant.evidence import build_packet
from warrant.paypal import PayPalClient, PayPalError
from warrant.scenarios import KeyBundle, build_scenarios, materialize

NOTE = "Warrant sandbox test."


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("show", "evidence", "refund", "offer"):
        sys.exit(__doc__)
    cmd, did = sys.argv[1], sys.argv[2]
    load_env()
    c = PayPalClient(os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_CLIENT_SECRET"],
                     os.environ.get("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com"))
    try:
        d = c.get_dispute(did)
        print(f"stage={d.get('dispute_life_cycle_stage')} status={d.get('status')} state={d.get('dispute_state')}")
        kb = KeyBundle.generate()
        spec = next(s for s in build_scenarios() if s["id"] == "regret-01")
        case = materialize(spec, kb)
        dec = rules_arbiter(case, Keys(kb.mandate_pub, kb.agent_pub))
        if cmd == "show":
            print("allowed:", json.dumps(d.get("allowed_response_options")))
            print("Warrant would do (for a within-mandate case):", plan_action(dec, d))
        elif cmd == "evidence":
            ev = plan_action(dec, d)["evidence_type"]
            print("result:", json.dumps(c.provide_evidence(did, build_packet(case, dec, Keys(kb.mandate_pub, kb.agent_pub), ev)))[:600])
        elif cmd == "refund":
            print("result:", json.dumps(c.accept_claim(did, NOTE))[:600])
        elif cmd == "offer":
            amt = d["dispute_amount"]
            print("result:", json.dumps(c.make_offer(did, NOTE, amt["value"], amt["currency_code"]))[:600])
    except PayPalError as e:
        print("FAIL:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()

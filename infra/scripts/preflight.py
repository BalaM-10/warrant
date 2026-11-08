"""Pre-recording check: run before every video take and before submitting.
Usage: python infra/scripts/preflight.py --url http://127.0.0.1:8000
Checks the health endpoint and that one scenario per outcome gets the expected verdict.
Add PayPal/LLM checks here as they are built."""
import argparse
import json
import sys
import urllib.request

EXPECT = {  # scenario id -> verdict
    "over-01": "OVERSTEPPED",
    "regret-01": "WITHIN_MANDATE",
    "merchant-01": "MERCHANT_FAULT",
    "tamper-01": "UNRESOLVED",
}


def call(url, method="GET"):
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    a = ap.parse_args()
    bad = 0
    try:
        ok = call(f"{a.url}/health").get("ok") is True
    except Exception as e:
        print(f"FAIL health: {e}")
        sys.exit(1)
    print("ok   health" if ok else "FAIL health")
    bad += not ok
    for sid, want in EXPECT.items():
        got = call(f"{a.url}/cases/{sid}/decide", "POST")["verdict"]
        print(("ok   " if got == want else "FAIL ") + f"{sid}: {got} (want {want})")
        bad += got != want
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

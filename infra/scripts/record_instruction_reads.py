"""Record real model reads of the demo instructions into data/instruction_reads.json (run once, needs
NVIDIA_API_KEY). Run from backend/:  python ../infra/scripts/record_instruction_reads.py
Commit the resulting file so reviewers without a key see recorded model output, labelled as recorded."""
import os
import sys

from warrant.config import load_env

load_env()
if not os.environ.get("NVIDIA_API_KEY"):
    sys.exit("Set NVIDIA_API_KEY in .env first.")

from warrant.instruction import default_reader  # noqa: E402

TEXTS = [
    "Buy USB-C cables from Test Store, up to $25, for 7 days.",
    "Buy USB-C cables from Test Store, up to $25, for 365 days.",
    "Buy office supplies from Test Store, up to $40, no more than $100 a week, for 30 days.",
    "Buy headphones from Test Store, up to $60, for 14 days.",
]
r = default_reader()
for t in TEXTS:
    out = r.read(t)
    print(f"{out['source']:<60} limit {out['limit']} stores {out['vendors']} items {out['categories']} "
          f"cap {out['window_cap']} days {out['valid_days']}\n   {t}")
print(f"{len(r.cache)} reads saved to {r.path}")

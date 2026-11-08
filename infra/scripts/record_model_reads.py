"""Record real model reads for the demo items into data/model_reads.json (run once, needs NVIDIA_API_KEY).
Run from backend/:  python ../infra/scripts/record_model_reads.py
Commit the resulting data/model_reads.json so reviewers without a key see recorded model output."""
import os
import sys

from warrant.config import load_env

load_env()
if not os.environ.get("NVIDIA_API_KEY"):
    sys.exit("Set NVIDIA_API_KEY in .env first.")

from warrant.console import Console  # noqa: E402
from warrant.modelreads import default_reads  # noqa: E402

reads = default_reads()
c = Console(reads=reads)  # reads every demo dispute's item
for title, cents in [("USB-C cable", 1250), ("Premium subscription trial", 999), ("Wireless earbuds bundle", 2200),
                     ("Laptop stand", 2000), ("Gift card", 2500), ("USB-C charger", 1500)]:
    c.preflight("Test Store", title, cents, "electronics_accessories")
print(f"{len(reads.cache)} reads saved to {reads.path}")
for k, v in sorted(reads.cache.items()):
    print(f"  {k.split('|')[0]:<30} {v['category']:<26} {v['confidence']}")

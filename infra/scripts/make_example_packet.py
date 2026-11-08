"""Regenerate docs/spec/examples/*.json from the scenario dataset. Run from backend/:
python ../infra/scripts/make_example_packet.py"""
import json
from pathlib import Path

from warrant.arbiter import Keys, rules_arbiter
from warrant.packet import build_json_packet
from warrant.scenarios import KeyBundle, build_scenarios, materialize

OUT = Path(__file__).resolve().parents[2] / "docs" / "spec" / "examples"
OUT.mkdir(parents=True, exist_ok=True)
kb = KeyBundle.generate()
keys = Keys(kb.mandate_pub, kb.agent_pub)
for name, sid in (("within-mandate", "regret-01"), ("overstepped", "over-01")):
    spec = next((s for s in build_scenarios() if s["id"] == sid), None)
    if not spec:
        continue
    case = materialize(spec, kb)
    pkt = build_json_packet(case, rules_arbiter(case, keys), keys, dispute_id="PP-R-EXAMPLE-0001", now=1_700_000_000)
    (OUT / f"{name}.json").write_text(json.dumps(pkt, indent=2))
    print("wrote", name, pkt["decision"]["verdict"])
(OUT / "public-keys.json").write_text(json.dumps(
    {"note": "Throwaway keys generated for this example only.",
     "mandate_public_key_pem": kb.mandate_pub.decode(), "agent_public_key_pem": kb.agent_pub.decode()}, indent=2))

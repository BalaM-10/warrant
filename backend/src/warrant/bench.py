"""Scorecard: compares rules-only, LLM-only and hybrid arbiters on our own scenarios."""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict

from .classify import keyword_classifier
from .arbiter import Keys, hybrid_arbiter, llm_only_arbiter, rules_arbiter
from .scenarios import KeyBundle, build_scenarios, materialize


def run(scenarios, kb: KeyBundle, arbiters: dict) -> list[dict]:
    keys = Keys(kb.mandate_pub, kb.agent_pub)
    rows = []
    for s in scenarios:
        case = materialize(s, kb)
        for name, fn in arbiters.items():
            d = fn(case, keys)
            rows.append(dict(id=s["id"], family=s["family"], split=s["split"], arbiter=name,
                             label=s["label"], predicted=d.verdict.value, codes=d.codes))
    return rows


def metrics(rows: list[dict], split: str = "all") -> dict:
    out = defaultdict(lambda: dict(n=0, agree=0, unsafe=0, guessed=0, should_unresolved=0))
    for r in rows:
        if split != "all" and r["split"] != split:
            continue
        m = out[r["arbiter"]]
        m["n"] += 1
        m["agree"] += r["predicted"] == r["label"]
        # Unsafe: refund offered or claim accepted when the agent stayed within its mandate.
        m["unsafe"] += r["label"] == "WITHIN_MANDATE" and r["predicted"] in ("OVERSTEPPED", "MERCHANT_FAULT")
        if r["label"] == "UNRESOLVED":
            m["should_unresolved"] += 1
            m["guessed"] += r["predicted"] != "UNRESOLVED"
    return dict(out)


def markdown(rows, classifier_name: str) -> str:
    lines = [f"# Warrant scorecard\n\nScenarios and labels are our own (n=36). Classifier: {classifier_name}.\n"]
    for split in ("report", "tune", "all"):
        m = metrics(rows, split)
        lines += [f"\n## Split: {split}\n", "| Arbiter | Cases | Agrees with label | Unsafe refunds/accepts | Guessed when it should hand off |",
                  "|---|---|---|---|---|"]
        for j, v in m.items():
            lines.append(f"| {j} | {v['n']} | {v['agree']}/{v['n']} | {v['unsafe']} | {v['guessed']}/{v['should_unresolved']} |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", choices=["none", "anthropic", "nvidia"], default="none")
    ap.add_argument("--model", default=None, help="model name for the chosen provider")
    ap.add_argument("--out", default="scorecard.md")
    ap.add_argument("--rows", default="scorecard_rows.json")
    a = ap.parse_args()
    from .config import load_env
    load_env()
    kb = KeyBundle.generate()
    arbiters = {"rules-only": rules_arbiter}
    if a.llm in ("anthropic", "nvidia"):
        import datetime
        from .llm import AnthropicLLM, OpenAICompatLLM, llm_classifier

        if a.llm == "nvidia":
            llm = OpenAICompatLLM(a.model or os.environ.get("NVIDIA_MODEL") or "nvidia/nemotron-3.5-bolt-e4b")
        else:
            llm = AnthropicLLM(a.model)
        arbiters["llm-only"] = lambda c, k: llm_only_arbiter(c, llm)
        arbiters["hybrid"] = lambda c, k: hybrid_arbiter(c, k, llm_classifier(llm))
        cname = f"LLM {llm.model} via {a.llm}, run {datetime.date.today()}"
    else:
        arbiters["hybrid (keyword stub)"] = lambda c, k: hybrid_arbiter(c, k, keyword_classifier)
        cname = "offline keyword stub (NOT the LLM; dry run only)"
    rows = run(build_scenarios(), kb, arbiters)
    if a.llm != "none":
        n_err = getattr(llm, "errors", 0)
        cname += f"; {getattr(llm, 'calls', '?')} model calls, {n_err} failed (a failed call counts as a hand-off to a human)"
    open(a.out, "w").write(markdown(rows, cname))
    json.dump(rows, open(a.rows, "w"), indent=1)
    print(markdown(rows, cname))


if __name__ == "__main__":
    main()

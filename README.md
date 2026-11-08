# Warrant

When a software agent buys the wrong thing, someone has to decide who was at fault. Warrant is that referee. It settles disputes over purchases made by software agents, and it runs on PayPal's sandbox.

**Try it:** https://warrant-30739400910.us-central1.run.app. No account or keys needed. Open Store owner to see four real PayPal sandbox disputes, one for each ruling, then Buyer for the other side and Developer to check an evidence packet for edits. The hosted copy shows recorded disputes, so approving there sends nothing to PayPal.

A buyer tells a shopping agent what it may buy, in plain English: "Buy USB-C cables from Test Store, up to $25, for 30 days." Warrant turns that into a signed instruction. The agent checks every cart against it, buys through PayPal's Orders API and signs a receipt. If the buyer later opens a dispute, Warrant reads the signed instruction, the receipt and the store's record, and reaches one of four rulings.

| Ruling | What Warrant does |
|---|---|
| Within mandate | Sends PayPal the signed instruction and receipt as evidence |
| Agent overstepped | Offers the buyer a refund |
| Merchant at fault | Accepts the claim and refunds the buyer |
| Needs a person | Hands the case to a person |

Limits, approved stores, dates, running totals and signatures are checked by ordinary code. A small language model does two jobs and never writes a ruling. When a buyer types an instruction, it reads the words into limits, stores and kinds of item, and the buyer confirms the reading before anything is signed. When a dispute comes in, it says what kind of item a cart line is, such as a cable or a subscription. If it isn't confident, the case goes to a person. Both jobs fall back to fixed code when no model is available, and the screen says which was used. The sentence explaining each ruling comes from a fixed list tied to reason codes, so the app can't give a reason the rules didn't find.

Warrant recommends and PayPal decides. The settle and adjudicate calls exist only in the sandbox.

## Scorecard

`python -m warrant.bench` compares three arbiters on 36 scenarios in 7 families: rules only, model only, and the two together. The scenarios and labels are ours. They are not ground truth from any real dispute system. We tuned on 12 and report on the other 24.

On those 24, rules alone agreed with our labels 21 times. A model alone agreed 11 times (Nemotron 3.5 Lightning, 30B) and 13 times (Nemotron 3.5 Bolt, 4B), and it never handed a case to a person. Rules plus model agreed 23 and 24 times. No arbiter made an unsafe refund. Each model was run once. Details and limits are in `docs/SCORECARD.md`.

Without `--llm` the benchmark uses a keyword stub, which only checks the wiring. Use `--llm nvidia` with a free key from build.nvidia.com, or `--llm anthropic`.

## Live mode

With PayPal sandbox keys in `.env`, the console runs the whole loop for real. The buyer's agent signs an instruction and buys a sandbox order. The buyer reports a problem in PayPal. Warrant loads that dispute, rules on it, and sends the real action when you approve. `docs/LIVE.md` has the steps. The queue holds only real sandbox disputes, and it is saved between restarts. Without keys, a copy shows the real disputes recorded from our own run (`data/recorded_disputes.json`, personal fields removed), labelled Recorded, and approving sends nothing. `infra/scripts/live_purchase.py` creates the real purchases and `infra/scripts/export_recorded.py` saves the recording.

## Demo roles

The console has a Viewing as switch with three roles: Store owner, Buyer and Developer. Each role shows only its own screens, which keeps a walkthrough to one story at a time. These are not accounts and nothing is protected by them.

## What you can reuse

- `docs/spec/` describes the evidence packet (v0.1): a JSON schema, examples and how to check a packet. The console can download a packet and check one for edits.
- `data/scenarios/` holds the 36 labelled scenarios. You can run them against your own arbiter.
- `python -m warrant.mcp_server` starts an MCP server with three tools: `decide_dispute`, `get_receipt` and `explain_dispute`.
- `docs/PAYPAL_FINDINGS.md` records what PayPal's sandbox does, checked live.
- `docs/RELATED_WORK.md` says what AP2, the Agent Commerce Kit and the Agentic Commerce Protocol propose for agent disputes, and where Warrant fits.

## Run

    cp .env.example .env   # add sandbox and NVIDIA keys; never commit this file
    cd backend && python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
    pytest
    uvicorn warrant.api:app --reload       # the API; build frontend/ first to serve the console at /
    python -m warrant.replay               # four outcomes on a recorded PayPal dispute, no account needed
    python ../infra/scripts/preflight.py   # with the server running
    python ../infra/scripts/live_check.py  # checks your PayPal sandbox keys

## Layout

    backend/    FastAPI app, arbiter, signing, PayPal client, benchmark, tests
    frontend/   React and AG Grid console: merchant queue, buyer view, packet check, buyer's agent
    infra/      Cloud Run deploy script, optional Render blueprint, checks and recording scripts
    Dockerfile  the one image that serves the API and the console
    data/       the scenario set and recorded item reads
    docs/       requirements and design notes

License: MIT.

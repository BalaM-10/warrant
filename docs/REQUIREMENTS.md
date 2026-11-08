# Warrant requirements (v1.3, frozen 2026-11-08)

Anything not listed under "In scope" is out. A change needs a written reason and has to remove something of equal size. Pushing the code to the public repo is the last step.

## Purpose

When a software agent buys something for a person and the purchase is disputed, someone has to decide who was right. Warrant is that referee. It runs on PayPal's sandbox, decides from signed evidence, and reports how well it decides.

## Users

- The buyer gives an agent a plain-English instruction, may file a dispute later, and wants a clear answer.
- The merchant receives disputes and wants to know which ones the agent legitimately made.
- A reviewer (hackathon judge, PayPal, other builders) wants to run the project, read it and reuse it.

## In scope

### R1. Mandate

A plain-English instruction becomes structured rules: a limit, approved vendors, allowed categories, a cumulative cap and window, and a validity period. The rules are stored as a signed token. Done when a tampered or wrongly signed mandate is rejected.

### R2. Agent purchase

A shopping agent buys through PayPal's sandbox Orders API and writes a signed receipt. The receipt holds the mandate hash, the cart, the total, what the buyer was told and any untrusted inputs the agent read. Done when a real sandbox order exists for each demo purchase.

### R3. Dispute loop

A dispute exists in PayPal's sandbox, Warrant reads it, decides, and acts through PayPal's Disputes API. The four outcomes and their actions:

- Overstepped: offer the buyer a refund.
- Within mandate: submit evidence.
- Merchant fault: accept the claim.
- Unresolved: hand the case to a person.

Done when all four outcomes have run end to end in the sandbox at least once and are recorded on video.

### R4. Arbiter

The hard rules are deterministic: limit, vendor, validity, cumulative cap and signatures. A model may only read language, at temperature 0: it classifies item categories (R4) and, from 2026-11-08, reads the buyer's typed instruction into rules (R18). It never rules on a dispute. Explanations come from fixed reason-code text, so a ruling can't cite a reason the rules didn't find. Version 1.1 said the model also wrote explanations. That was never built, and the fixed text is the safer design, so this entry was corrected on 2026-11-05. Missing, tampered or low-confidence cases go to a person, and the arbiter never guesses. Done when every ruling shows its reason codes and a plain-language explanation.

### R5. Evidence packet

For within-mandate disputes, Warrant builds the packet (mandate, receipt, decision, notes) and submits it to PayPal.

### R6. Merchant console

A dispute queue built with AG Grid, showing the ruling, reason codes, recommended action and a control to approve or override. Done when a merchant can clear all four outcome types.

### R7. Buyer view

The buyer sees what they authorized, what the agent did, the ruling and a plain explanation, with no jargon.

### R8. Scorecard

Three arbiters (rules only, model only, and both together) run on 36 scenarios in 7 families. Labels were frozen on Day 5. We tune on 12 scenarios and report on the other 24. The metrics are agreement with the labels, unsafe refunds or accepts, guesses that should have been hand-offs, and a 1-to-5 human rating of 10 explanations. Every table says "on our own scenarios".

### R9. Open assets

A versioned evidence-packet spec (JSON schema plus examples, shaped after AP2), the scenario dataset with a command to run your own arbiter, and a processor-neutral adapter interface with PayPal as the only live integration. The second-processor stub was dropped in v1.1 to make room for R11.

### R10. Delivery

A public GitHub repo with a visible MIT license, a README that runs from a clean machine, a hosted demo (Render or Cloud Run), a public YouTube video under 3 minutes, and the Devpost text. Submit by the evening of Nov 11. The deadline is Nov 12, 12:00 PM PT.

### R11. MCP server

The tools `decide_dispute`, `get_receipt` and `explain_dispute` are exposed over MCP so any agent can call Warrant. Done when an MCP client lists the tools and gets a ruling for a demo dispute.

### R12. Preflight check

Before an agent buys, the same rules engine checks the cart against the mandate and returns allow, block or ask a person. Done when an over-limit cart is blocked in the demo without reaching PayPal.

### R13. Evidence clock and audit trail

The merchant console shows PayPal's response deadline for each dispute, plus a history of every decision and human override: who, when and what.

## Added in v1.2

These four were agreed on 2026-11-05 after a full review. R18 was added on 2026-11-08.

### R14. Real model in the demo

The console recognises items with a hosted model. It uses recorded reads when no key is set and live calls when one is. It shows how confident the read was, and the demo includes a prompt-injection dispute. Done when a reviewer without keys sees recorded reads, labelled as recorded.

### R15. Live PayPal mode

Paste a real sandbox dispute id. Warrant fetches it and decides, and approving sends the real action. Done when an approval in the console changes a real sandbox dispute. This was done on 2026-11-05.

### R16. Buyer flow

Type an instruction and see it signed. The agent buys a real sandbox order and the signed receipt is stored. Done when a real sandbox order has a receipt that Warrant can later find from a dispute. This was done on 2026-11-05.

### R17. Packet download and check

Download an evidence packet and check its hash and signatures. Done when an edited packet fails the check.

### R18. Instruction reading (added 2026-11-08)

A model reads the buyer's typed instruction into limits, stores, kinds of item, a running cap and a duration. The reading is checked against the buyer's own words (a limit or store that isn't in the text is rejected), shown on screen, and signed only after the buyer confirms it. If no model is available or the answer fails the checks, a fixed pattern reader is used and the screen says so. Done when a reviewer without a key sees recorded reads labelled as recorded, and a made-up number from a model is refused.

To make room for the added work, there is no webhook receiver, no sponsor-API integration and no second processor.

## Out of scope

- Real money or production PayPal.
- Settlement logic. The sandbox settle call is used only to simulate PayPal.
- Live merchant onboarding.
- User accounts and login beyond the sandbox buyer credentials.
- SD-JWT or full AP2 conformance.
- Multiple currencies.
- A mobile app.
- A second processor, live or stub.
- Coaching for writing instructions.
- Merchant analytics and savings calculators.
- Training or fine-tuning models.
- Any claim of real-world accuracy.

## Rules we hold to

- Warrant recommends and submits, and PayPal decides. Say so everywhere.
- No secrets in the repo; keys live in `.env` only. No InfoVision material. Personal time and equipment.
- The scenario labels are the author's own, and the README says so.
- Anything the sandbox can't do is shown as such and never faked.

## Definition of done

A fresh clone passes `pytest`, and one command (`python -m warrant.replay`) shows the four outcomes on a recorded real PayPal sandbox dispute with no account needed. That replay is labelled "recorded". With their own sandbox keys in `.env`, a reviewer can also run the same loop live by following the README: create a test order, then report a problem as the buyer.

## Known risks that could force a cut

If sandbox dispute creation or evidence submission misbehaves by the end of Day 3, fall back to showing Warrant's decision together with the API calls it would make, labelled as such. R13 and then R12 are the first things cut if time runs short. R3 is never cut.

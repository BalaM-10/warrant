# Evidence packet v0.1

An open record of a disputed purchase made by a software agent, usable with any payment processor. It borrows from AP2, which has an intent mandate and a signed purchase record. It does not conform to AP2: it uses plain ES256 JWTs and no SD-JWT.

## Why it exists

When an agent buys something and the buyer disputes it, three parties each hold part of the story: the buyer's instruction, the agent's record of what it did, and the merchant's delivery record. A packet puts all three in one file, with enough evidence for anyone to check it without trusting whoever wrote it.

## What is in it

| Field | Meaning |
|---|---|
| `spec` | Always `warrant.evidence-packet/0.1`. |
| `processor` | The payment processor and the dispute id. Nothing else in the packet depends on the processor. |
| `claim` | What the buyer says: reason, statement and amount in cents. |
| `mandate` | The buyer's signed instruction. It holds the JWT as issued, plus the decoded claims if the signature verified. |
| `receipt` | The agent's signed record of the purchase, in the same shape. |
| `merchant_record` | What the merchant reports, for example `delivery_status`. |
| `prior_purchases` | Earlier purchases under the same instruction, used for cumulative caps. |
| `checks` | `valid`, `invalid` or `missing` for each signature. |
| `decision` | The ruling, reason codes, a plain explanation, whether a model's read was used, and the recommended action. |
| `packet_sha256` | The SHA-256 of the packet without this field, written as JSON with sorted keys and no spaces. |

## Rulings

The four rulings are `WITHIN_MANDATE`, `OVERSTEPPED`, `MERCHANT_FAULT` and `UNRESOLVED`. If a signature is missing or invalid, or the rules can't settle the case, the ruling must be `UNRESOLVED`. An arbiter never guesses.

## How to check a packet

1. Validate it against `evidence-packet.schema.json`.
2. Recompute `packet_sha256` and compare it with the stored value.
3. Verify `mandate.token` with the public key of whoever issued the instruction, and `receipt.token` with the agent's public key. Expiry is not checked at dispute time. Whether the purchase fell inside the time window is a rule applied to the purchase time.
4. Run your own arbiter on the packet and compare rulings. The scenarios in `data/scenarios` and `python -m warrant.bench` do this for the Warrant arbiter.

## Limits

A packet shows what was signed and when. It doesn't prove the item arrived, and `merchant_record` is only as reliable as the merchant. The ruling is a recommendation, and the processor makes the decision.

The `examples/` folder has sample packets and throwaway public keys to verify them. To regenerate them, run `python ../infra/scripts/make_example_packet.py` from `backend/`. A test checks that packets validate against the schema and that any edit breaks the hash.

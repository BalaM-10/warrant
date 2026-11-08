# Related work

Disputes over purchases made by software agents are a known gap. This page says what already exists, what is still a proposal, and where Warrant fits. Everything here was checked on 2026-11-08. These projects move quickly, so check the links before relying on them.

## What exists

**Agent Payments Protocol (AP2).** Google's open protocol defines signed mandates: an intent mandate for purchases made while the buyer is away, and a cart mandate for purchases the buyer approves. PayPal's developer blog says it supports AP2 and proposes adding mandates to Seller Protection and dispute workflows, so merchants can submit stronger evidence. That post describes plans and pilots. It does not describe a tool that decides disputes.

**Agent Commerce Kit, dispute evidence proposal.** Issue 217 in the `agentcommercekit/ack` repository proposes a `dispute+jwt` artifact that carries a grant, a receipt and the difference between them, with reason codes such as `scope-exceeded` and `grant-expired`. It is a working draft, and it covers the evidence format and a mechanical check. It does not say who decides a dispute or how.

**Agentic Commerce Protocol, dispute extension.** Pull request 316 in the `agentic-commerce-protocol` repository proposes an optional dispute resolution extension for scope, performance, intent and amount disputes. At the time of writing it was open, and it says a reference implementation exists but is not part of the proposal.

**Arbitration services.** DecisionLayer offers arbitration for agent disputes through an MCP server, with a human arbitrator issuing the award. Its published fees start at $500 and its target is 45 days, which suits large commercial disputes more than a $12 cable.

## Where Warrant fits

The proposals above define evidence formats. Warrant is a working referee that reads that kind of evidence and acts on it:

- It runs against PayPal's real sandbox Orders and Disputes APIs and sends the action the ruling calls for.
- It reaches one of four rulings from signed evidence, and hands the case to a person when the evidence is missing or doesn't check out.
- It measures itself. The scorecard compares rules only, a model only and both together on 36 scenarios we wrote.
- It publishes its evidence packet as a small open spec, so another arbiter can be run on the same packets.

## How the formats line up

Warrant's packet is a plain ES256 JWT format shaped after AP2. It is not AP2 conformant. The reason codes map roughly like this:

| Warrant reason code | Closest ACK reason code |
|---|---|
| `OVER_LIMIT`, `OVER_WINDOW_CAP` | `scope-exceeded` |
| `OUTSIDE_VALIDITY` | `grant-expired` |
| `VENDOR_NOT_APPROVED` | `audience-mismatch` |
| `RECEIPT_MANDATE_MISMATCH` | `unauthorized-agent` (close, not the same) |
| `CATEGORY_NOT_ALLOWED` | none. ACK leaves category mismatches out because a machine can't check them from the artifacts alone |

The last row is the one Warrant works on. Category mismatches need someone to read what was bought, which is where Warrant uses a language model (it also reads the buyer's typed instruction, before signing). It hands the case to a person when the model isn't confident.

## What Warrant does not do

It does not settle money, and it does not replace PayPal's decision. It has no webhook receiver yet, it supports one currency, and its scorecard uses our own labels, so it says nothing about accuracy on real disputes.

## Links

- Google AP2 and PayPal's post: https://developer.paypal.com/community/blog/PayPal-Agent-Payments-Protocol/
- ACK dispute evidence proposal: https://github.com/agentcommercekit/ack/issues/217
- ACP dispute extension proposal: https://github.com/agentic-commerce-protocol/agentic-commerce-protocol/pull/316
- DecisionLayer: https://dev.to/scriptmasterlabs01/how-does-the-decisionlayer-mcp-server-work-4-arbitration-actions-a-signed-form-rule-and-a-live-hdf

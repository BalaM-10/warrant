# Live mode: the full loop on PayPal's sandbox

Live mode turns on by itself when `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET` (sandbox) are in `.env`.
It keeps its signing keys and records in `backend/live_state/`, which git ignores. A receipt written when
the agent buys is still there when the dispute arrives, even after a restart.

1. In the Buyer's agent tab, type an instruction and sign it, then enter a cart. A cart over the limit or
   from another store is blocked without any call to PayPal. An allowed cart creates a real sandbox order.
2. Open the PayPal link, sign in as the sandbox buyer and approve. Back in the console, finish the
   purchase. The agent captures the payment and stores a signed receipt under PayPal's payment id.
3. In the PayPal sandbox, as the buyer, open the Resolution Center and report "I haven't received the item".
   PayPal's API can't create sandbox disputes, so this one step is done by hand. Copy the case id (PP-R-...).
4. In the Merchant console, paste the case id, say what your store recorded, and load it. Warrant fetches
   the real dispute, finds the receipt and rules. A new dispute stays "under PayPal review" for a few
   minutes with no seller actions allowed. Until PayPal opens it, Warrant hands the case to a person. Load it again after a few minutes.
5. Approve sends the real action to the sandbox: evidence, a refund offer, or accepting the claim.
   Overrides are recorded only and are never sent to PayPal.

Status: the whole loop was run once on 2026-11-05 against the real sandbox. A $1.00 order was bought,
disputed as not received, loaded in the console, ruled within mandate and sent to PayPal on approval.
PayPal moved the dispute from "waiting for seller response" to "under review". The refund and
accept-claim actions were verified earlier, one call at a time (see PAYPAL_FINDINGS.md).

To record the model's item reads for the demo, run `python ../infra/scripts/record_model_reads.py`.
It needs `NVIDIA_API_KEY` and writes `data/model_reads.json`. Commit that file so people without a key
see the recorded reads, labelled as recorded.

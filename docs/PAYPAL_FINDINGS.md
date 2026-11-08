# What the PayPal sandbox does (checked live, 2026-11-04 and 2026-11-05)

- Orders: create, buyer approval (sandbox Personal account) and capture all work with the app's keys.
- Disputes access works once the Disputes feature is switched on for the app.
- A buyer-filed "item not received" report in the sandbox Resolution Center creates a dispute with an id
  like `PP-R-XXX-########`, in stage INQUIRY with status WAITING_FOR_SELLER_RESPONSE.
- `GET /v1/customer/disputes/{id}` returns it, including `allowed_response_options`
  (accept_claim: REFUND or PARTIAL_REFUND; make_offer: REFUND), the action links (provide_evidence,
  accept_claim, escalate, send_message, make_offer) and a `REQUESTED_FROM_SELLER` evidence request of
  type PROOF_OF_FULFILLMENT.
- `GET /v1/customer/disputes` returned an empty list a few minutes after creation, even though the
  dispute existed. Treat listing as unreliable until retested. Fetch by id, or use webhooks
  (CUSTOMER.DISPUTE.CREATED).
- Evidence upload (multipart PDF, PROOF_OF_FULFILLMENT) works.
- make_offer (REFUND, full amount) and accept_claim (REFUND) both work. They were verified on
  PP-R-GVN-10196710 and PP-R-AOY-10196711. Each call returns only a `links` list, so fetch the dispute again to see the result.
- A new dispute sits in `UNDER_PAYPAL_REVIEW` with `allowed_response_options: null` for a few minutes.
  Acting during that time returns 422 `ACTION_NOT_ALLOWED_IN_...`. Warrant reads the allowed options first.
  If none are allowed it hands the case to a person, and the live session script waits for the options to appear.
- A new dispute has no `seller_response_due_date` yet. The console shows "Not set" until PayPal gives one
  (it asks again every 30 seconds while the queue is open) and never invents a date.
- The `seller_transaction_id` on the dispute equals the capture id from the Orders API, which is how Warrant
  finds its receipt. The buyer's own transaction id, used in the Resolution Center link, is a different id.
- Timestamps include milliseconds, for example `2026-11-24T23:56:38.276Z`.

A recorded copy of a real response is in `backend/tests/fixtures/dispute_inquiry.json`.

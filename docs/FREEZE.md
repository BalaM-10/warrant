# Feature freeze, 2026-11-08

From this point the app changes only for bugs, wrong text and anything the video or the rules need. A new feature needs a written reason and has to remove something of equal size.

## What is in

- The signed instruction: the buyer types it, a model reads it, the buyer confirms the reading, Warrant signs it (R1, R18).
- The agent's cart check before buying, and real sandbox purchases with a signed receipt (R2, R12, R16).
- The four rulings and the actions they call for, including live PayPal sandbox disputes (R3, R4, R15).
- The evidence packet, with download and a check that catches edits (R5, R17).
- The console with three roles: Store owner, Buyer and Developer (R6, R7, R13).
- The scorecard on 36 scenarios with two models (R8).
- The MCP server, the open spec and the scenario set (R9, R11).

## What is out

A webhook receiver, a second payment processor, real accounts, other currencies, and any claim about accuracy on real disputes.

## What was checked at freeze

- 31 tests pass. A fresh install from the zip passes them too, and `python -m warrant.replay` shows the four outcomes.
- Every role view was scanned for accessibility problems at desktop and phone width, with none found, and the browser console is clean.
- Every line of text on screen was swept for dashes, stock phrases and exclamation marks, with none found.
- Bad input was tried on every endpoint. It found zero and negative prices passing the cart check, and a missing length limit on typed text. Both are fixed and covered by tests.
- A scan of the repo found no keys or secrets.

## Still to do outside the code

Deploy to Render, record the video, finish the Devpost form, check the employment agreement, regenerate the shared keys, and make the repo public last.


## Amended 2026-11-08 (late)

The queue no longer holds seeded demo disputes. It shows real PayPal sandbox disputes (saved between restarts) or, on a copy with no keys, real disputes recorded from our own run. The video is shot on real sandbox disputes. Added `live_purchase.py`, `export_recorded.py` and a recorded desk. The seeded disputes remain only in tests, `warrant.replay` and the MCP server.

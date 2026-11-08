# Warrant console (frontend)

React, Vite and TypeScript, with AG Grid. It has four views: the merchant dispute queue, the buyer view,
a packet checker, and the buyer's agent. It talks to the backend over `/api`.

    cd frontend && npm install
    npm run dev        # http://localhost:5173, proxies /api to the backend on :8000
    npm run build      # then the backend serves the built console at http://localhost:8000

Fonts (Schibsted Grotesk and Source Serif 4) are bundled with the app, so the console makes no
third-party requests.

The queue shows demo data unless live mode is on. The demo disputes use the shape of a recorded PayPal
sandbox response, with ids, amounts and deadlines changed. We seeded the instructions and receipts, and
the console says so. Approve and override are dry runs unless the backend has a live PayPal client.

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .console import Console

from .classify import keyword_classifier
from .arbiter import Keys, hybrid_arbiter
from .scenarios import KeyBundle, build_scenarios, materialize

app = FastAPI(title="Warrant")
_kb = KeyBundle.generate()
_specs = {s["id"]: s for s in build_scenarios()}


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/scenarios")
def scenarios():
    return [{k: s[k] for k in ("id", "family", "split", "label", "label_note")} for s in _specs.values()]


@app.post("/cases/{sid}/decide")
def decide_case(sid: str):
    if sid not in _specs:
        raise HTTPException(404, "unknown scenario")
    d = hybrid_arbiter(materialize(_specs[sid], _kb), Keys(_kb.mandate_pub, _kb.agent_pub), keyword_classifier)
    return {"verdict": d.verdict, "action": d.action, "codes": d.codes, "explanation": d.explanation}


app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
console = Console(seed_disputes=os.environ.get("WARRANT_SEED_DEMO") == "1")


class Who(BaseModel):
    actor: str = "merchant"


class Override(Who):
    action: str
    note: str = ""


def _get(did):
    return did


@app.get("/api/disputes")
def api_queue():
    return console.queue() + _queue_desks()


@app.get("/api/disputes/{did}")
def api_detail(did: str):
    return _desk(did).detail(did)


@app.get("/api/disputes/{did}/packet")
def api_packet(did: str):
    from fastapi.responses import JSONResponse
    return JSONResponse(_desk(did).packet(did),
                        headers={"Content-Disposition": f'attachment; filename="warrant-packet-{did}.json"'})


@app.post("/api/packets/verify")
def api_verify_packet(packet: dict):
    from .packet import verify_packet
    desks = [console] + ([live] if live else []) + ([recorded] if recorded else [])
    return verify_packet(packet, [d.keys for d in desks])


@app.post("/api/disputes/{did}/approve")
def api_approve(did: str, b: Who):
    return _desk(did).approve(did, b.actor)


@app.post("/api/disputes/{did}/override")
def api_override(did: str, b: Override):
    try:
        return _desk(did).override(did, b.actor, b.action, b.note)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/buyer/{did}")
def api_buyer(did: str):
    return _desk(did).buyer_view(did)


class Cart(BaseModel):
    vendor: str = Field("Test Store", max_length=100)
    title: str = Field(max_length=200)
    price: float = Field(gt=0, le=1_000_000)
    category: str = "electronics_accessories"
    mandate_id: str | None = None


@app.post("/api/preflight")
def api_preflight(c: Cart):
    try:
        return console.preflight(c.vendor, c.title, round(c.price * 100), c.category, c.mandate_id)
    except Exception:
        raise HTTPException(400, "That signed instruction was not found. Sign it again.")


# ---- live PayPal sandbox mode (R15, R16): only when sandbox keys are set
from .config import load_env  # noqa: E402

load_env()
live = None
if os.environ.get("PAYPAL_CLIENT_ID") and os.environ.get("PAYPAL_CLIENT_SECRET"):
    from .live import LiveDesk
    from .paypal import PayPalClient
    live = LiveDesk(PayPalClient(os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_CLIENT_SECRET"],
                                 os.environ.get("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com")))


recorded = None
if not live:  # no PayPal keys: show the real disputes recorded from our own sandbox run, if the file is there
    from .recorded import RecordedDesk
    recorded = RecordedDesk.load()
if live:
    try:
        live.restore()
    except Exception:
        pass  # a broken saved file should not stop the server


def _queue_desks():
    return (live.queue() if live else []) + (recorded.queue() if recorded else [])


def _live():
    if not live:
        raise HTTPException(503, "Live mode needs your PayPal sandbox keys in .env, then restart the server.")
    return live


class MandateIn(BaseModel):
    instruction: str = Field(max_length=1000)
    fields: dict | None = None  # the reading the buyer confirmed on screen


class PurchaseIn(BaseModel):
    mandate_id: str
    title: str = Field(max_length=200)
    price: float = Field(gt=0, le=1_000_000)
    vendor: str = Field("Test Store", max_length=100)
    category: str = "electronics_accessories"


class LoadIn(BaseModel):
    dispute_id: str
    delivery: str = "unknown"


@app.get("/api/live/status")
def api_live_status():
    return {"enabled": bool(live), "recorded": bool(recorded)}


@app.post("/api/live/mandates")
def api_live_mandate(b: MandateIn):
    """Kept for scripts: sign an instruction on the live desk only."""
    try:
        return _live().create_mandate(b.instruction)
    except ValueError as e:
        raise HTTPException(400, str(e))


def _buyer_desk():
    return live if live else console


@app.post("/api/instruction/read")
def api_read_instruction(b: MandateIn):
    """Step one of the buyer flow: a model (or the fixed reader) reads the instruction. Nothing is signed."""
    try:
        return _buyer_desk().read_instruction(b.instruction)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/mandates")
def api_mandate(b: MandateIn):
    """Step two: sign the instruction. The confirmed reading is checked against the text again."""
    try:
        from .instruction import InstructionReader
        f = InstructionReader.to_fields(b.fields) if b.fields else None
        return _buyer_desk().create_mandate(b.instruction, fields=f)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/live/purchases")
def api_live_purchase(b: PurchaseIn):
    try:
        return _live().start_purchase(b.mandate_id, b.vendor, b.title, b.price, b.category)
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/live/purchases/{order_id}/finish")
def api_live_finish(order_id: str):
    try:
        return _live().finish_purchase(order_id)
    except KeyError:
        raise HTTPException(404, "Unknown order. Start the purchase again.")
    except Exception as e:
        raise HTTPException(400, f"PayPal did not capture it yet. Approve the payment in PayPal first. ({e})")


@app.post("/api/live/disputes")
def api_live_load(b: LoadIn):
    try:
        return _live().load_dispute(b.dispute_id.strip(), b.delivery)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"Could not load that dispute from PayPal. ({e})")


def _desk(did: str):
    if did in console.disputes:
        return console
    if live and did in live.disputes:
        return live
    if recorded and did in recorded.disputes:
        return recorded
    raise HTTPException(404, "unknown dispute")


# One-server demo: if the console has been built (npm run build in frontend/), serve it at /.
_dist = os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend", "dist")
if os.path.isdir(_dist):
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=_dist, html=True), name="console")

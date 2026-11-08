import json
import httpx
import pytest

from warrant.bench import metrics, run
from warrant.classify import keyword_classifier
from warrant.evidence import build_packet
from warrant.arbiter import Keys, hybrid_arbiter, rules_arbiter, Verdict
from warrant.mandate import MandateError, generate_keypair, sign_mandate, verify_mandate, Mandate
from warrant.paypal import PayPalClient
from warrant.scenarios import FAMILIES, KeyBundle, build_scenarios, materialize

KB = KeyBundle.generate()
KEYS = Keys(KB.mandate_pub, KB.agent_pub)
SPECS = {s["id"]: s for s in build_scenarios()}


def test_dataset_shape():
    s = build_scenarios()
    assert len(s) == 36 and len({x["id"] for x in s}) == 36
    for name, n, t in FAMILIES:
        fam = [x for x in s if x["family"] == name]
        assert len(fam) == n and sum(x["split"] == "tune" for x in fam) == t
    assert sum(x["split"] == "tune" for x in s) == 12


def test_mandate_roundtrip_and_wrong_key():
    priv, pub = generate_keypair()
    _, other_pub = generate_keypair()
    m = Mandate("m1", "b", "buy cable", "USD", 2500, ["v"], ["c"], not_before=1, not_after=2)
    tok = sign_mandate(m, priv)
    assert verify_mandate(tok, pub).max_total_cents == 2500  # expired by now, still verifiable
    with pytest.raises(MandateError):
        verify_mandate(tok, other_pub)
    with pytest.raises(MandateError):
        verify_mandate(None, pub)


def test_rules_arbiter_gets_every_deterministic_family_right_and_misses_injection():
    rows = run(build_scenarios(), KB, {"rules": rules_arbiter})
    wrong = {r["id"] for r in rows if r["predicted"] != r["label"]}
    assert wrong == {"inject-01", "inject-02", "inject-03", "inject-04"}


def test_hybrid_stub_matches_all_labels():
    rows = run(build_scenarios(), KB, {"h": lambda c, k: hybrid_arbiter(c, k, keyword_classifier)})
    assert [r["id"] for r in rows if r["predicted"] != r["label"]] == []


def test_low_confidence_goes_to_human():
    spec = json.loads(json.dumps(SPECS["regret-01"]))
    spec["purchase"]["items"][0]["title"] = "mystery item"
    d = hybrid_arbiter(materialize(spec, KB), KEYS, keyword_classifier)
    assert d.verdict == Verdict.UNRESOLVED and d.codes == ["CLASSIFIER_LOW_CONFIDENCE"]


def test_tamper_cases_never_guess():
    for sid in ("tamper-01", "tamper-02", "tamper-03", "tamper-04", "tamper-05"):
        assert rules_arbiter(materialize(SPECS[sid], KB), KEYS).verdict == Verdict.UNRESOLVED


def test_metrics_unsafe_and_guessed():
    rows = [dict(id="a", family="f", split="report", arbiter="j", label="WITHIN_MANDATE", predicted="OVERSTEPPED", codes=[]),
            dict(id="b", family="f", split="report", arbiter="j", label="UNRESOLVED", predicted="WITHIN_MANDATE", codes=[])]
    m = metrics(rows)["j"]
    assert (m["unsafe"], m["guessed"], m["agree"]) == (1, 1, 0)


def test_evidence_packet():
    case = materialize(SPECS["regret-01"], KB)
    d = rules_arbiter(case, KEYS)
    p = build_packet(case, d, KEYS)
    assert p["evidence_type"] == "PROOF_OF_FULFILLMENT" and len(p["notes"]) <= 2000
    name, data, mime = p["files"][0]
    assert mime == "application/pdf" and data.startswith(b"%PDF") and data.rstrip().endswith(b"%%EOF")
    assert "within it" in p["notes"]


def test_paypal_client_with_mock_transport():
    seen = []

    def handler(req: httpx.Request):
        seen.append((req.method, req.url.path, req.headers.get("authorization")))
        if req.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(200, json={"id": "D-1", "status": "OK"})

    c = PayPalClient("id", "secret", transport=httpx.MockTransport(handler))
    c.get_dispute("D-1")
    c.make_offer("D-1", "n", "19.99", "USD")
    c.provide_evidence("D-1", {"evidence_type": "OTHER", "notes": "x", "files": [("a.json", b"{}", "application/json")]})
    assert [p for _, p, _ in seen].count("/v1/oauth2/token") == 1  # token cached
    assert seen[-1][1].endswith("/provide-evidence") and seen[-1][2] == "Bearer tok"


def test_plan_action_against_real_dispute_fixture():
    import copy, pathlib
    from warrant.actions import plan_action
    from warrant.arbiter import Decision
    d = json.loads((pathlib.Path(__file__).parent / "fixtures" / "dispute_inquiry.json").read_text())
    mk = lambda v, codes=(): Decision(v, list(codes), "")
    assert plan_action(mk(Verdict.WITHIN_MANDATE), d) == {"action": "provide_evidence", "evidence_type": "PROOF_OF_FULFILLMENT"}
    assert plan_action(mk(Verdict.MERCHANT_FAULT, ["NOT_DELIVERED"]), d)["reason"] == "DID_NOT_SHIP_ITEM"
    assert plan_action(mk(Verdict.OVERSTEPPED), d)["action"] == "make_offer"
    assert plan_action(mk(Verdict.UNRESOLVED), d)["action"] == "escalate_to_human"
    # if PayPal does not allow the action, hand to a human instead of failing
    d2 = copy.deepcopy(d)
    d2["allowed_response_options"] = {}
    assert plan_action(mk(Verdict.OVERSTEPPED), d2)["action"] == "escalate_to_human"
    d2["links"] = []
    assert plan_action(mk(Verdict.WITHIN_MANDATE), d2)["action"] == "escalate_to_human"


def test_preflight_blocks_and_allows():
    from warrant.arbiter import preflight
    from warrant.mandate import verify_mandate
    case = materialize(SPECS["regret-01"], KB)
    m = verify_mandate(case.mandate_token, KB.mandate_pub)
    from warrant.receipt import verify_receipt
    r = verify_receipt(case.receipt_token, KB.agent_pub)
    assert preflight(m, r, [])["decision"] == "allow"
    import dataclasses
    over = dataclasses.replace(r, total_cents=9999)
    out = preflight(m, over, [])
    assert out["decision"] == "block" and "OVER_LIMIT" in out["codes"]


def test_replay_gets_all_four_outcomes_and_audit_log():
    from warrant.replay import run
    got = {r["variant"]: (r["verdict"], r["plan"]["action"]) for r in run()}
    assert got["within mandate, delivered"] == ("WITHIN_MANDATE", "provide_evidence")
    assert got["merchant never delivered"] == ("MERCHANT_FAULT", "accept_claim")
    assert got["agent over the limit (limit $0.50)"] == ("OVERSTEPPED", "make_offer")
    assert got["no receipt on file"] == ("UNRESOLVED", "escalate_to_human")


def test_handle_dispute_executes_through_client_and_logs():
    import json, pathlib
    from warrant.replay import FIXTURE, seed
    from warrant.service import handle_dispute
    from warrant.store import Store
    calls = []

    class Fake:
        def provide_evidence(self, did, packet):
            calls.append((did, packet["evidence_type"], len(packet["files"])))
            return {"ok": True}

    d = json.loads(FIXTURE.read_text())
    kb, store = KeyBundle.generate(), Store()
    seed(store, kb, d)
    res = handle_dispute(d, store, Keys(kb.mandate_pub, kb.agent_pub), keyword_classifier, client=Fake(), execute=True)
    assert res["executed"] and calls == [("PP-R-JZZ-10196453", "PROOF_OF_FULFILLMENT", 1)]
    log = store.decisions("PP-R-JZZ-10196453")
    assert len(log) == 1 and log[0]["verdict"] == "WITHIN_MANDATE" and log[0]["executed"] == 1


def test_live_session_flow_with_mock_paypal(tmp_path):
    import httpx, json
    from warrant.live_session import run
    seq = {"orders": 0}
    approved = {}
    log = []

    def handler(req: httpx.Request):
        p, m = req.url.path, req.method
        log.append((m, p))
        if p == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if p == "/v2/checkout/orders" and m == "POST":
            seq["orders"] += 1
            oid = f"ORD{seq['orders']}"
            return httpx.Response(200, json={"id": oid, "status": "PAYER_ACTION_REQUIRED",
                                             "links": [{"rel": "payer-action", "href": f"https://x/{oid}"}]})
        if p.startswith("/v2/checkout/orders/") and p.endswith("/capture"):
            return httpx.Response(200, json={"purchase_units": [{"payments": {"captures": [{"id": "CAP" + p.split("/")[4]}]}}]})
        if p.startswith("/v2/checkout/orders/") and m == "GET":
            return httpx.Response(200, json={"status": "APPROVED"})
        if p.endswith("/make-offer") or p.endswith("/accept-claim"):
            return httpx.Response(200, json={"links": []})
        if p.startswith("/v1/customer/disputes/") and m == "GET":
            return httpx.Response(200, json={"status": "WAITING_FOR_SELLER_RESPONSE", "dispute_state": "REQUIRED_ACTION",
                                             "dispute_life_cycle_stage": "INQUIRY",
                                             "allowed_response_options": {"make_offer": {}, "accept_claim": {}},
                                             "dispute_amount": {"currency_code": "USD", "value": "1.00"}})
        return httpx.Response(404, json={})

    c = PayPalClient("id", "secret", transport=httpx.MockTransport(handler))
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps({"1": "PP-R-A", "2": "PP-R-B"}))
    state = run(c, tmp_path / "state.json", cases, sleep=lambda s: None, poll=0, log=lambda *_: None)
    assert state["stage"] == "done"
    assert [o["status"] for o in state["orders"]] == ["COMPLETED", "COMPLETED"]
    assert ("POST", "/v1/customer/disputes/PP-R-A/make-offer") in log
    assert ("POST", "/v1/customer/disputes/PP-R-B/accept-claim") in log
    assert json.loads((tmp_path / "state.json").read_text())["stage"] == "done"


def test_agent_parse_preflight_and_purchase():
    import httpx
    from warrant.agent import Agent, issue_mandate, parse_mandate
    from warrant.mandate import generate_keypair
    from warrant.paypal import PayPalClient
    from warrant.store import Store
    m = parse_mandate("Buy USB-C cables from Test Store, up to $25, no more than $40 a day, for 3 days.", "b1", now=1000)
    assert (m.max_total_cents, m.allowed_vendors, m.window_cap_cents) == (2500, ["Test Store"], 4000)
    assert m.allowed_categories == ["electronics_accessories"] and m.not_after == 1000 + 3 * 86400
    try:
        parse_mandate("buy me stuff", "b1"); assert False
    except ValueError:
        pass
    calls = []

    def h(req):
        p = req.url.path; calls.append(p)
        if p.endswith("/token"): return httpx.Response(200, json={"access_token": "t", "expires_in": 300})
        if p.endswith("/orders"): return httpx.Response(201, json={"id": "O1", "links": [{"rel": "approve", "href": "http://x"}]})
        if p.endswith("/capture"): return httpx.Response(201, json={"purchase_units": [{"payments": {"captures": [{"id": "C1"}]}}]})
        return httpx.Response(404, json={})
    mp, mu = generate_keypair(); ap, au = generate_keypair()
    store = Store()
    now = 1_700_000_000
    m, _ = issue_mandate("Buy USB-C cables from Test Store, up to $25, for 3 days.", "b1", store, mp, now=now)
    ag = Agent(store, PayPalClient("i", "s", transport=httpx.MockTransport(h)), mu, ap, clock=lambda: now + 60)
    item = {"title": "USB-C cable", "price_cents": 1999, "qty": 1}
    over = ag.start_purchase(m.mandate_id, "Test Store", [dict(item, price_cents=9999)], "electronics_accessories")
    assert over["status"] == "block" and "OVER_LIMIT" in over["codes"] and not any("orders" in c for c in calls)
    ok = ag.start_purchase(m.mandate_id, "Test Store", [item], "electronics_accessories")
    assert ok["status"] == "awaiting_buyer_approval" and ok["order_id"] == "O1"
    done = ag.finish_purchase("O1")
    assert done["capture_id"] == "C1" and store.find_receipt_by_capture("C1")["total_cents"] == 1999


def test_console_queue_actions_and_audit():
    from fastapi.testclient import TestClient
    from warrant.api import app
    c = TestClient(app)
    q = c.get("/api/disputes").json()
    assert {r["verdict"] for r in q} == {"WITHIN_MANDATE", "MERCHANT_FAULT", "OVERSTEPPED", "UNRESOLVED"} and len(q) == 5
    assert all(r["days_left"] > 0 and r["action_text"] for r in q)
    did = next(r["dispute_id"] for r in q if r["verdict"] == "OVERSTEPPED")
    d = c.get(f"/api/disputes/{did}").json()
    assert d["mandate"]["signature"] == "valid" and d["receipt"]["signature"] == "valid"
    assert c.post(f"/api/disputes/{did}/approve", json={"actor": "bala"}).json()["state"] == "approved"
    assert c.post(f"/api/disputes/{did}/override", json={"actor": "bala", "action": "bogus"}).status_code == 400
    audit = c.get(f"/api/disputes/{did}").json()["audit"]
    assert [a["actor"] for a in audit] == ["warrant", "bala"]
    assert "refund" in c.get(f"/api/buyer/{did}").json()["plain"]


def test_console_detail_keeps_each_disputes_own_records():
    from warrant.console import Console
    c = Console()
    seen = {}
    for r in c.queue():
        d = c.detail(r["dispute_id"])
        seen[r["verdict"]] = (d["mandate"]["signature"], d["receipt"]["signature"])
    assert seen["UNRESOLVED"] == ("missing", "missing")  # no receipt links this payment to any mandate
    assert seen["WITHIN_MANDATE"] == seen["MERCHANT_FAULT"] == seen["OVERSTEPPED"] == ("valid", "valid")


def test_vendor_shown_as_store_name():
    from warrant.console import Console
    c = Console()
    d = c.detail(c.queue()[0]["dispute_id"])
    assert d["receipt"]["vendor"] == "Test Store"


def test_preflight_endpoint_blocks_over_limit_without_paypal():
    from fastapi.testclient import TestClient
    from warrant.api import app
    c = TestClient(app)
    ok = c.post("/api/preflight", json={"title": "USB-C cable", "price": 12.5}).json()
    assert ok["status"] == "allow" and ok["reached_paypal"] is False
    bad = c.post("/api/preflight", json={"title": "USB-C cable", "price": 99}).json()
    assert bad["status"] == "block" and "OVER_LIMIT" in bad["codes"]
    store = c.post("/api/preflight", json={"title": "x", "price": 5, "vendor": "Shady Shop"}).json()
    assert "VENDOR_NOT_APPROVED" in store["codes"]


def test_openai_compat_llm_retries_and_classifies():
    import httpx
    from warrant.llm import OpenAICompatLLM, llm_classifier
    seen = []

    def h(req):
        import json as j
        body = j.loads(req.content); seen.append(body)
        if len(seen) == 1:
            return httpx.Response(429, json={})
        return httpx.Response(200, json={"choices": [{"message": {"content": 'ok {"category": "electronics_accessories", "confidence": 0.9}'}}]})
    import os
    os.environ["NVIDIA_API_KEY"] = "test"
    llm = OpenAICompatLLM("m", transport=httpx.MockTransport(h), sleep=lambda s: None)
    cat, conf = llm_classifier(llm)("USB-C cable", ["electronics_accessories"])
    assert (cat, conf) == ("electronics_accessories", 0.9) and len(seen) == 2
    assert seen[0]["temperature"] == 0 and seen[0]["chat_template_kwargs"] == {"enable_thinking": False}


def test_packet_matches_schema_and_hash_detects_tampering():
    import json
    from pathlib import Path
    import jsonschema
    from warrant.arbiter import Keys, rules_arbiter
    from warrant.packet import build_json_packet, verify_packet_hash
    from warrant.scenarios import KeyBundle, build_scenarios, materialize
    schema = json.loads((Path(__file__).resolve().parents[2] / "docs/spec/evidence-packet.schema.json").read_text())
    kb = KeyBundle.generate(); keys = Keys(kb.mandate_pub, kb.agent_pub)
    kinds = set()
    for sid in ("regret-01", "inject-01"):
        spec = next(s for s in build_scenarios() if s["id"] == sid)
        case = materialize(spec, kb)
        pkt = build_json_packet(case, rules_arbiter(case, keys), keys, dispute_id="D1", now=1_700_000_000)
        jsonschema.validate(pkt, schema)
        assert verify_packet_hash(pkt); kinds.add(pkt["decision"]["verdict"])
        pkt["decision"]["verdict"] = "OVERSTEPPED" if pkt["decision"]["verdict"] != "OVERSTEPPED" else "WITHIN_MANDATE"
        assert not verify_packet_hash(pkt)
    # a case with no mandate or receipt still yields a valid packet marked missing
    from warrant.arbiter import Case, Claim
    empty = Case(None, None, Claim("OTHER"))
    pkt = build_json_packet(empty, rules_arbiter(empty, keys), keys)
    jsonschema.validate(pkt, schema)
    assert pkt["checks"] == {"mandate_signature": "missing", "receipt_signature": "missing"}
    assert pkt["decision"]["verdict"] == "UNRESOLVED"


def test_model_reads_cache_live_and_stub(tmp_path):
    from warrant.modelreads import Reads
    live_calls = []

    def live(title, allowed):
        live_calls.append(title)
        return ("services", 0.9)
    allowed = ["electronics_accessories"]
    r = Reads(tmp_path / "r.json", live_classifier=live, model="m1")
    assert r.classify("Premium trial", allowed) == ("services", 0.9) and live_calls == ["Premium trial"]
    assert r.classify("Premium trial", allowed) == ("services", 0.9) and len(live_calls) == 1  # cached
    assert "m1, recorded" in r.take()[-1]["source"]
    r2 = Reads(tmp_path / "r.json")  # a reviewer with no key still gets the recorded read
    assert r2.classify("Premium trial", allowed) == ("services", 0.9)
    assert "recorded" in r2.take()[0]["source"]
    r3 = Reads(tmp_path / "none.json")  # nothing cached, no key: stub, clearly labelled
    r3.classify("USB-C cable", allowed)
    assert r3.take()[0]["source"].startswith("keyword stub")
    failing = Reads(tmp_path / "f.json", live_classifier=lambda t, a: ("other", 0.0), model="m1")
    failing.classify("x", allowed)
    assert not (tmp_path / "f.json").exists()  # failed reads are never cached


def test_live_desk_buyer_to_dispute_to_real_action(tmp_path):
    """Mocked PayPal: mandate -> blocked cart -> real order -> capture -> receipt -> dispute -> approve sends evidence."""
    import copy, json
    import httpx
    from pathlib import Path
    from warrant.live import LiveDesk
    from warrant.modelreads import Reads
    from warrant.paypal import PayPalClient
    base = json.loads((Path(__file__).parent / "fixtures" / "dispute_inquiry.json").read_text())
    log = []
    state = {"after": False}

    def h(req):
        p, m = req.url.path, req.method
        log.append((m, p))
        if p.endswith("/token"): return httpx.Response(200, json={"access_token": "t", "expires_in": 300})
        if p.endswith("/orders"): return httpx.Response(201, json={"id": "O9", "links": [{"rel": "payer-action", "href": "http://pay"}]})
        if p.endswith("/capture"): return httpx.Response(201, json={"purchase_units": [{"payments": {"captures": [{"id": "CAP9"}]}}]})
        if p.endswith("/provide-evidence"):
            state["after"] = True
            return httpx.Response(200, json={"links": []})
        if "/disputes/PP-R-LIVE-1" in p and m == "GET":
            d = copy.deepcopy(base); d["dispute_id"] = "PP-R-LIVE-1"
            d["disputed_transactions"][0]["seller_transaction_id"] = "CAP9"
            if state["after"]: d["status"], d["dispute_state"] = "UNDER_REVIEW", "UNDER_PAYPAL_REVIEW"
            return httpx.Response(200, json=d)
        return httpx.Response(404, json={})
    client = PayPalClient("i", "s", transport=httpx.MockTransport(h))
    desk = LiveDesk(client, state_dir=tmp_path, reads=Reads(tmp_path / "r.json"))
    m = desk.create_mandate("Buy USB-C cables from Test Store, up to $25, for 3 days.")
    assert m["signed"] and m["limit"] == 25.0
    blocked = desk.start_purchase(m["mandate_id"], "Test Store", "USB-C cable", 99.0, "electronics_accessories")
    assert blocked["status"] == "block" and not any("orders" in p for _, p in log)
    ok = desk.start_purchase(m["mandate_id"], "Test Store", "USB-C cable", 12.5, "electronics_accessories")
    assert ok["approve_url"] == "http://pay"
    done = desk.finish_purchase(ok["order_id"])
    assert done["capture_id"] == "CAP9"
    # the dispute arrives; the merchant says it was delivered
    row = desk.load_dispute("PP-R-LIVE-1", delivery="delivered")
    assert row["verdict"] == "WITHIN_MANDATE" and row["source"] == "live" and row["state"] == "pending"
    out = desk.approve("PP-R-LIVE-1", "bala")
    assert ("POST", "/v1/customer/disputes/PP-R-LIVE-1/provide-evidence") in log
    assert out["paypal_status"]["dispute_state"] == "UNDER_PAYPAL_REVIEW" and out["state"] == "approved"
    assert desk.store.decisions("PP-R-LIVE-1")[-1]["executed"] == 1
    # the same keys and records survive a restart
    again = LiveDesk(client, state_dir=tmp_path, reads=Reads(tmp_path / "r.json"))
    assert again.store.find_receipt_by_capture("CAP9")["total_cents"] == 1250
    assert again.load_dispute("PP-R-LIVE-1")["verdict"] == "WITHIN_MANDATE"


def test_live_endpoints_say_why_when_not_configured():
    from fastapi.testclient import TestClient
    import warrant.api as api
    old, api.live = api.live, None
    try:
        c = TestClient(api.app)
        assert c.get("/api/live/status").json()["enabled"] is False
        r = c.post("/api/live/mandates", json={"instruction": "x"})
        assert r.status_code == 503 and "sandbox keys" in r.json()["detail"]
    finally:
        api.live = old


def test_packet_download_and_verify_catches_edits():
    import json
    from fastapi.testclient import TestClient
    from warrant.api import app
    c = TestClient(app)
    r = c.get("/api/disputes/PP-R-DEMO-103/packet")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    pkt = r.json()
    assert pkt["decision"]["verdict"] == "OVERSTEPPED"
    ok = c.post("/api/packets/verify", json=pkt).json()
    assert ok["ok"] is True and ok["hash"] == "ok" and ok["mandate_signature"] == "valid"
    pkt["decision"]["verdict"] = "WITHIN_MANDATE"   # someone edits the ruling
    bad = c.post("/api/packets/verify", json=pkt).json()
    assert bad["ok"] is False and bad["hash"] == "broken"
    pkt2 = c.get("/api/disputes/PP-R-DEMO-103/packet").json()
    pkt2["receipt"]["token"] = pkt2["receipt"]["token"][:-4] + "AAAA"   # a forged receipt token, hash recomputed
    import hashlib
    body = {k: v for k, v in pkt2.items() if k != "packet_sha256"}
    pkt2["packet_sha256"] = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    forged = c.post("/api/packets/verify", json=pkt2).json()
    assert forged["hash"] == "ok" and forged["receipt_signature"] != "valid" and forged["ok"] is False


def test_new_paypal_inquiry_without_due_date_still_loads():
    """A freshly filed dispute has no seller_response_due_date yet; the row still builds and shows no deadline."""
    from warrant.console import Console
    c = Console()
    d = dict(c.disputes["PP-R-DEMO-101"])
    d.pop("seller_response_due_date")
    d["create_time"] = "2026-11-06T03:22:43.276Z"
    c.disputes["PP-R-DEMO-101"] = d
    row = c._row("PP-R-DEMO-101")
    assert row["due"] is None and row["days_left"] is None
    assert c.queue()[-1]["dispute_id"] == "PP-R-DEMO-101"  # no deadline sorts last


def test_history_does_not_repeat_identical_recommendations():
    from warrant.store import Store
    s = Store()
    for _ in range(3):
        s.log_decision("D1", "warrant", "WITHIN_MANDATE", ["WITHIN_MANDATE"], {"action": "provide_evidence"}, False, "")
    s.log_decision("D1", "Bala", "WITHIN_MANDATE", ["WITHIN_MANDATE"], {"action": "provide_evidence"}, True, "approved")
    s.log_decision("D1", "warrant", "WITHIN_MANDATE", ["WITHIN_MANDATE"], {"action": "provide_evidence"}, False, "")
    assert [r["actor"] for r in s.decisions("D1")] == ["warrant", "Bala", "warrant"]


def test_instruction_reading_checks_the_model_against_the_buyers_words(tmp_path):
    import json
    from warrant.agent import validate_fields
    from warrant.instruction import InstructionReader
    text = "Please buy USB-C cables from Test Store, up to $25, for 3 days."
    good = {"max_total": 25, "vendors": ["Test Store"], "categories": ["electronics_accessories"],
            "window_cap": None, "window_hours": 24, "valid_days": 3}
    # a model that invents a limit, a store or an item kind is rejected
    for bad in (dict(good, max_total=250), dict(good, vendors=["Other Shop"]), dict(good, categories=["weapons"]),
                dict(good, valid_days=4000), dict(good, vendors=[])):
        try:
            validate_fields(text, bad); assert False, bad
        except ValueError:
            pass
    calls = []

    def model(system, user):
        calls.append(user); return "Sure! " + json.dumps(good)
    r = InstructionReader(tmp_path / "i.json", llm=model, model="nvidia/test-model")
    out = r.read(text)
    assert out["model_used"] and out["limit"] == 25.0 and out["valid_days"] == 3 and "live" in out["source"]
    # the second read comes from the recording, and a reader with no model still shows it as recorded
    again = InstructionReader(tmp_path / "i.json").read(text)
    assert again["model_used"] and "recorded" in again["source"] and len(calls) == 1
    # a model that makes up a number falls back to the fixed reader, and the screen says so
    liar = InstructionReader(tmp_path / "j.json", llm=lambda s, u: json.dumps(dict(good, max_total=999)), model="m")
    out = liar.read(text)
    assert not out["model_used"] and out["limit"] == 25.0 and "did not match" in out["source"]
    # an unusable answer does the same, and no model at all says there is no key
    assert "did not match" in InstructionReader(tmp_path / "k.json", llm=lambda s, u: "no idea", model="m").read(text)["source"]
    assert "no model key" in InstructionReader(tmp_path / "l.json").read(text)["source"]
    try:
        InstructionReader(tmp_path / "m.json").read("buy me stuff"); assert False
    except ValueError:
        pass


def test_demo_buyer_signs_what_was_read_and_the_check_uses_it(tmp_path):
    from warrant.console import Console
    from warrant.instruction import InstructionReader
    from warrant.modelreads import Reads
    c = Console(reads=Reads(tmp_path / "r.json"), reader=InstructionReader(tmp_path / "i.json"))
    text = "Buy USB-C cables from Test Store, up to $15, for 3 days."
    view = c.read_instruction(text)
    assert view["limit"] == 15.0
    m = c.create_mandate(text, fields=InstructionReader.to_fields(view))
    assert m["limit"] == 15.0 and m["signed"]
    over = c.preflight("Test Store", "USB-C cable", 2000, "electronics_accessories", m["mandate_id"])
    assert over["status"] == "block" and "OVER_LIMIT" in over["codes"] and over["mandate"] == text
    # the demo's own instruction still allows the same cart
    assert c.preflight("Test Store", "USB-C cable", 2000, "electronics_accessories")["status"] == "allow"
    # a reading that does not match the words is refused at signing
    try:
        c.create_mandate(text, fields=InstructionReader.to_fields(dict(view, limit=500.0))); assert False
    except ValueError:
        pass


def test_carts_with_zero_or_negative_prices_are_refused(tmp_path):
    from fastapi.testclient import TestClient
    import warrant.api as api
    from warrant.console import Console
    from warrant.modelreads import Reads
    c = TestClient(api.app)
    for price in (-5, 0):
        assert c.post("/api/preflight", json={"title": "cable", "price": price}).status_code == 422
    assert c.post("/api/instruction/read", json={"instruction": "x" * 5000}).status_code == 422
    desk = Console(reads=Reads(tmp_path / "r.json"))
    try:
        desk.preflight("Test Store", "USB-C cable", -500, "electronics_accessories"); assert False
    except ValueError:
        pass


def test_scrub_removes_personal_fields():
    from warrant.recorded import scrub
    out = scrub({"payer": {"email_address": "a@b.com", "payer_id": "X1", "name": {"given_name": "Ann"}},
                 "messages": [{"content": "mail me at ann@example.org"}], "amount": "1.00"})
    s = json.dumps(out)
    assert "a@b.com" not in s and "X1" not in s and "Ann" not in s and "ann@example.org" not in s
    assert out["amount"] == "1.00"


def test_recorded_desk_decides_from_exported_file(tmp_path):
    import base64
    from warrant.recorded import RecordedDesk
    from warrant.replay import FIXTURE, seed
    from warrant.scenarios import KeyBundle
    from warrant.store import Store
    dispute = json.loads(FIXTURE.read_text())
    kb, store = KeyBundle.generate(), Store()
    seed(store, kb, dispute, max_cents=50)
    cap = dispute["disputed_transactions"][0]["seller_transaction_id"]
    rec = store.find_receipt_by_capture(cap)
    data = {"keys": {"mandate_pub": base64.b64encode(kb.mandate_pub).decode(), "agent_pub": base64.b64encode(kb.agent_pub).decode()},
            "disputes": [{"dispute": dispute, "mandate_id": rec["mandate_id"], "mandate_token": store.get_mandate_token(rec["mandate_id"]),
                          "receipt": rec, "fulfilment": store.get_fulfilment(rec["order_id"])}]}
    p = tmp_path / "r.json"
    p.write_text(json.dumps(data))
    desk = RecordedDesk.load(p)
    row = desk.queue()[0]
    assert row["source"] == "recorded" and row["verdict"] == "OVERSTEPPED"
    assert row["days_left"] is not None
    assert desk.approve(row["dispute_id"], "merchant")["state"] == "approved"
    assert RecordedDesk.load(tmp_path / "missing.json") is None


def test_live_desk_keeps_disputes_across_restarts(tmp_path):
    from warrant.live import LiveDesk
    from warrant.replay import FIXTURE
    d = json.loads(FIXTURE.read_text())

    class Fake:
        def get_dispute(self, did):
            return d
    a = LiveDesk(Fake(), tmp_path)
    a.load_dispute(d["dispute_id"])
    b = LiveDesk(Fake(), tmp_path)
    assert b.restore() == 1 and d["dispute_id"] in b.disputes


def test_approved_dispute_keeps_its_action_when_paypal_moves_on():
    from warrant.console import Console
    c = Console()
    did = next(r["dispute_id"] for r in c.queue() if r["action"] != "escalate_to_human")
    before = c._row(did)["action"]
    c.approve(did, "Store owner")
    moved = {**c.disputes[did], "status": "UNDER_PAYPAL_REVIEW", "dispute_life_cycle_stage": "UNDER_REVIEW"}
    c._decide(moved)
    assert c._row(did)["action"] == before
    assert [a["note"] for a in c.store.decisions(did)].count("needs human") == 0


def test_live_desk_restores_approved_even_when_nothing_was_sent(tmp_path):
    from warrant.live import LiveDesk
    from warrant.replay import FIXTURE
    d = json.loads(FIXTURE.read_text())

    class C:
        def get_dispute(self, did): return d
    desk = LiveDesk(C(), state_dir=tmp_path)
    desk._decide(d); desk._remember(d)
    did = d["dispute_id"]
    desk.store.log_decision(did, "Store owner", "UNRESOLVED", [], {"action": "escalate_to_human"}, False,
                            "approved; recorded only, nothing was sent to PayPal")
    again = LiveDesk(C(), state_dir=tmp_path)
    again.restore()
    assert again.state[did] == "approved"

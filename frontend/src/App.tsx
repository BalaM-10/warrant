import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import type { ColDef } from "ag-grid-community";
import { api, BASE, Audit, Buyer, Check, Detail, ItemRead, MandateView, Purchase, Row, Understood, Verdict, Verified } from "./api";

const VERDICT: Record<Verdict, { name: string; cls: string }> = {
  WITHIN_MANDATE: { name: "Within mandate", cls: "v-within" },
  OVERSTEPPED: { name: "Agent overstepped", cls: "v-over" },
  MERCHANT_FAULT: { name: "Merchant at fault", cls: "v-fault" },
  UNRESOLVED: { name: "Needs a person", cls: "v-unres" },
};
const ACTIONS: [string, string][] = [
  ["provide_evidence", "Send evidence to PayPal"], ["accept_claim", "Accept claim and refund"],
  ["make_offer", "Offer a refund"], ["escalate_to_human", "Hand to a person"],
];
const ACTION_LABEL: Record<string, string> = {
  provide_evidence: "send evidence to PayPal", accept_claim: "accept the claim and refund", make_offer: "offer a refund", escalate_to_human: "hand to a person",
};
const SHORT: Record<string, string> = { provide_evidence: "Send evidence", accept_claim: "Accept and refund", make_offer: "Offer a refund", escalate_to_human: "Hand to a person" };
const LEGEND: Record<Verdict, string> = {
  WITHIN_MANDATE: "The agent bought what the buyer allowed. Warrant sends PayPal the signed proof.",
  OVERSTEPPED: "The agent went past a limit the buyer set. Warrant offers the buyer a refund.",
  MERCHANT_FAULT: "The agent was within bounds but the store did not deliver. Warrant accepts the claim.",
  UNRESOLVED: "The records are missing or conflict. Warrant never guesses, so a person decides.",
};
const REASON: Record<string, string> = { CLASSIFIER_LOW_CONFIDENCE: "item unclear" };
const STATE_TEXT = { pending: "Waiting for you", approved: "Approved", overridden: "Overridden" };
const CAT: Record<string, string> = { electronics_accessories: "electronics accessory", services: "service or subscription", gift_cards: "gift card",
  audio: "audio gear", office_supplies: "office supplies", computers: "computer", other: "something we could not place" };

const PATHS: Record<string, string> = {
  check: "M4 8.5l2.8 2.8L12 4.8",
  x: "M4.5 4.5l7 7M11.5 4.5l-7 7",
  doc: "M4 1.8h5.2L12.2 4.8v9.4H4zM9 1.8v3.2h3.2M6 8h4M6 10.5h4",
  clock: "M8 3.2V8l3 1.8",
  alert: "M8 4.5v4M8 11v.1",
};
function Icon({ n }: { n: keyof typeof PATHS }) {
  return (
    <svg className="i" viewBox="0 0 16 16" aria-hidden="true">
      {n === "clock" && <circle cx="8" cy="8" r="6.2" />}
      {n === "alert" && <circle cx="8" cy="8" r="6.2" />}
      <path d={PATHS[n]} />
    </svg>
  );
}
function Mark() {
  return (
    <svg className="i" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="10.5" /><path d="M6.8 14.6c1.4-3.4 3-5.4 4.4-5.4s.5 4.2 2 4.2 2.4-2 3-3.6" />
    </svg>
  );
}

function daysText(d: number) { return d >= 1 ? `${Math.floor(d)} days${Math.floor(d) < 3 ? ` ${Math.round((d % 1) * 24)} h` : ""}` : `${Math.round(d * 24)} h`; }
function Clock({ days }: { days: number | null }) {
  if (days === null) return <span className="clock"><Icon n="clock" />PayPal has not set a deadline yet</span>;
  return <span className={"clock" + (days < 3 ? " urgent" : "")}><Icon n="clock" />{daysText(days)} to answer PayPal</span>;
}
const money = (n?: number) => (n === undefined ? "" : "$" + n.toFixed(2));

function Reading({ items }: { items: ItemRead[] }) {
  if (!items.length) return null;
  return (
    <div>
      {items.map((i, n) => (
        <p key={n} className="reading">{i.item}: {CAT[i.category] ?? i.category}, {Math.round(i.confidence * 100)}% sure</p>
      ))}
    </div>
  );
}

function History({ items }: { items: Audit[] }) {
  const rows = items.filter((a, i) => !(i > 0 && a.actor === "warrant" && items[i - 1].actor === "warrant" &&
    items[i - 1].action === a.action && items[i - 1].note === a.note));
  return (
    <ol className="timeline">
      {rows.map((a, i) => {
        const label = ACTION_LABEL[JSON.parse(a.action).action] ?? "";
        const warrant = a.actor === "warrant";
        return (
          <li key={i} className={warrant ? "" : "by-person"}>
            <time>{new Date(a.ts * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}</time>
            {warrant ? <>Warrant recommended to {label}</> : <><b>{a.actor}</b> chose to {label}</>}
            {a.note && !warrant ? <span className="note">{a.note}</span> : null}
          </li>
        );
      })}
    </ol>
  );
}

function Seal({ ok, what }: { ok: boolean; what: string }) {
  return <div className={"seal" + (ok ? "" : " bad")}><Icon n={ok ? "check" : "x"} />{ok ? "Signature verified" : `No signed ${what.toLowerCase()} on file`}</div>;
}

function Merchant({ d, onChange }: { d: Detail; onChange: () => void }) {
  const [who, setWho] = useState(() => localStorage.getItem("who") || "Store owner");
  const [choice, setChoice] = useState(ACTIONS[0][0]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const run = async (f: () => Promise<unknown>) => {
    setBusy(true); setErr("");
    try { localStorage.setItem("who", who); await f(); onChange(); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  };
  const done = d.state !== "pending";
  const v = VERDICT[d.verdict];
  const m = d.mandate, r = d.receipt;
  const delivery = Object.keys(d.fulfilment).length ? String((d.fulfilment as any).delivery_status).replace("_", " ") : "";
  const sends = d.source === "live" && d.action !== "escalate_to_human";
  return (
    <article className={"file " + v.cls.replace("v-", "s-")}>
      <section>
        <div className="file-top"><span className="id">{d.dispute_id}</span><Clock days={d.days_left} /></div>
        <h2 className={"ruling-name " + v.cls}>{v.name}</h2>
        <p className="why">{d.explanation}</p>
        <div className="reco"><small>Warrant recommends</small><strong>{d.action_text}</strong></div>
        <a className="packet-link" href={`${BASE}/api/disputes/${d.dispute_id}/packet`} download><Icon n="doc" />Download the evidence packet</a>
        {d.source === "live" && d.paypal_status && (
          <p className="pp">PayPal status: {d.paypal_status.status?.replaceAll("_", " ").toLowerCase()}.</p>
        )}
        <p className="codes">{d.codes.length ? "Reason: " + d.codes.map(c => REASON[c] ?? c.toLowerCase().replaceAll("_", " ")).join(", ") : "No rule broken"}</p>
      </section>

      <section>
        <h3 className="sec">What the buyer said</h3>
        <p className="said">“{d.buyer_said}”</p>
      </section>

      <section>
        <h3 className="sec">The record</h3>
        <div className="sheets">
          <div className="instrument">
            <h4>Buyer's instruction</h4>
            {m?.instruction ? (
              <>
                <p className="signed">“{m.instruction}”</p>
                <dl>
                  {m.limit !== undefined && <><dt>Limit</dt><dd>{money(m.limit)}</dd></>}
                  {!!m.vendors?.length && <><dt>Store</dt><dd>{m.vendors.map(x => (x.includes("@") ? "Test Store" : x)).join(", ")}</dd></>}
                  {!!m.categories?.length && <><dt>Items</dt><dd>{m.categories.map(c => CAT[c] ?? c).join(", ")}</dd></>}
                </dl>
              </>
            ) : <p className="nothing">There is no signed instruction for this purchase.</p>}
            <Seal ok={m?.signature === "valid"} what="Instruction" />
          </div>
          <div className="instrument">
            <h4>Agent's receipt</h4>
            {r?.items ? (
              <>
                <p className="signed">{r.items.map(i => `${i.qty} × ${i.title}`).join(", ")}</p>
                <dl>
                  <dt>Store</dt><dd>{r.vendor}</dd>
                  <dt>Total</dt><dd>{money(r.total)}</dd>
                  {r.told_buyer && <><dt>Told buyer</dt><dd className="quote">“{r.told_buyer}”</dd></>}
                  {r.why && <><dt>Reason</dt><dd>{r.why}</dd></>}
                </dl>
                {!!r.untrusted_inputs?.length && <p className="flag"><Icon n="alert" />The agent read outside content: {r.untrusted_inputs.join(", ")}.</p>}
              </>
            ) : <p className="nothing">There is no signed receipt for this purchase.</p>}
            <Seal ok={r?.signature === "valid"} what="Receipt" />
          </div>
        </div>
        <dl className="facts">
          <dt>Disputed amount</dt><dd>{d.currency === "USD" ? "$" : d.currency + " "}{d.amount}</dd>
          <dt>Store's record</dt><dd>{delivery || "Nothing recorded"}</dd>
          {d.item_reads.length > 0 && <><dt>Item reading</dt><dd><Reading items={d.item_reads} /></dd></>}
        </dl>
      </section>

      <section className="decide">
        <h3 className="sec">Your decision</h3>
        {done ? (
          <p className="done"><Icon n="check" /><span>{STATE_TEXT[d.state]}. PayPal makes the final decision.</span></p>
        ) : (
          <div className="stack">
            <label>Your name<input value={who} placeholder="Name for the history" onChange={e => setWho(e.target.value)} /></label>
            <button className="btn primary" disabled={busy || !who.trim()} onClick={() => run(() => api.approve(d.dispute_id, who.trim()))}>
              {sends ? "Approve and send to PayPal sandbox" : "Approve"}: {d.action_text.charAt(0).toLowerCase() + d.action_text.slice(1)}
            </button>
            <details className="alt">
              <summary>Choose a different action</summary>
              <div className="stack">
                <select value={choice} onChange={e => setChoice(e.target.value)} aria-label="Different action">{ACTIONS.map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select>
                <input placeholder="Why are you overriding?" value={note} onChange={e => setNote(e.target.value)} />
                <button className="btn" disabled={busy || !who.trim() || !note.trim()} onClick={() => run(() => api.override(d.dispute_id, who.trim(), choice, note))}>Override</button>
              </div>
            </details>
          </div>
        )}
        {err && <p className="error">{err}</p>}
      </section>

      <section>
        <h3 className="sec">History</h3>
        <History items={d.audit} />
        <p className="fine">{d.data_note}</p>
      </section>
    </article>
  );
}

function BuyerView({ id }: { id: string }) {
  const [b, setB] = useState<Buyer | null>(null);
  useEffect(() => { api.buyer(id).then(setB); }, [id]);
  if (!b) return null;
  return (
    <div className="page letter">
      <h2>What happened with your purchase</h2>
      <section><h3 className="sec">You told your agent</h3><p className="said">“{b.you_allowed ?? "We have no record of an instruction."}”</p></section>
      <section>
        <h3 className="sec">Your agent</h3>
        <p>{b.agent_did?.items ? <>Bought {b.agent_did.items.map(i => i.title).join(", ")} from {b.agent_did.vendor} for {money(b.agent_did.total)}. It told you: <span className="said">“{b.agent_did.told_buyer}”</span></> : "We cannot find a record of this purchase."}</p>
      </section>
      <section>
        <h3 className="sec">What we found</h3>
        <p className={"found " + VERDICT[b.verdict].cls}>{b.plain}</p>
        <p style={{ marginTop: 10 }}>{b.reasons}</p>
      </section>
      <p className="fine">PayPal makes the final decision on your dispute.</p>
    </div>
  );
}

const CHECK_TEXT = { allow: "Allowed. The agent can buy this.", block: "Blocked before it reached PayPal.", ask_human: "The agent stops and asks you first." };
const DEFAULT_INSTRUCTION = "Buy USB-C cables from Test Store, up to $25, for 7 days.";

function BuyerAgent({ live }: { live: boolean }) {
  const [instruction, setInstruction] = useState(DEFAULT_INSTRUCTION);
  const [read, setRead] = useState<Understood | null>(null);
  const [mandate, setMandate] = useState<MandateView | null>(null);
  const [vendor, setVendor] = useState("Test Store");
  const [title, setTitle] = useState("USB-C cable");
  const [price, setPrice] = useState("12.50");
  const [res, setRes] = useState<Check | null>(null);
  const [order, setOrder] = useState<Purchase | null>(null);
  const [done, setDone] = useState<Purchase | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const wrap = async (f: () => Promise<void>) => { setBusy(true); setErr(""); try { await f(); } catch (e) { setErr(readError(e)); } finally { setBusy(false); } };
  const reset = () => { setRead(null); setMandate(null); setRes(null); setOrder(null); setDone(null); };
  const understand = () => wrap(async () => { reset(); setRead(await api.readInstruction(instruction)); });
  const sign = () => wrap(async () => { setMandate(await api.mandate(instruction, read!)); setRes(null); setOrder(null); setDone(null); });
  const demoCheck = () => wrap(async () => setRes(await api.preflight({ vendor, title, price: Number(price), mandate_id: mandate!.mandate_id })));
  const buy = () => wrap(async () => {
    setDone(null); setOrder(null); setRes(null);
    const p = await api.livePurchase({ mandate_id: mandate!.mandate_id, title, price: Number(price), vendor });
    if (p.status === "awaiting_buyer_approval") setOrder(p);
    else setRes({ status: p.status as Check["status"], codes: p.codes ?? [], explanation: p.explanation ?? "", mandate: mandate!.instruction, reached_paypal: false, item_reads: p.item_reads ?? [] });
  });
  const finish = () => wrap(async () => { setDone(await api.liveFinish(order!.order_id!)); setOrder(null); });
  return (
    <div className="page">
      <h2>{live ? "Your agent buys for you" : "Try a purchase"}</h2>
      <p>Your agent checks every cart against what you allowed before it spends anything.</p>
      <div className="form">
        <label>What may your agent buy?<textarea rows={2} value={instruction} onChange={e => { setInstruction(e.target.value); reset(); }} /></label>
        <button className="btn primary inline" disabled={busy || !instruction.trim()} onClick={understand}>Read my instruction</button>
        {read && !mandate && (
          <div className="result ok">
            <h3>This is what your agent understood</h3>
            <dl className="understood">
              <dt>Limit</dt><dd>{money(read.limit)} per purchase</dd>
              <dt>Stores</dt><dd>{read.vendors.join(", ")}</dd>
              <dt>Items</dt><dd>{read.categories.map(c => CAT[c] ?? c).join(", ") || "any kind"}</dd>
              {read.window_cap ? <><dt>Running total</dt><dd>{money(read.window_cap)} every {read.window_hours === 168 ? "week" : read.window_hours === 24 ? "day" : `${read.window_hours} hours`}</dd></> : null}
              <dt>Lasts</dt><dd>{read.valid_days} {read.valid_days === 1 ? "day" : "days"}</dd>
            </dl>
            <p className="subtle">{readSource(read)}</p>
            <button className="btn primary inline" disabled={busy} onClick={sign}>That is right. Sign it</button>
            <p className="subtle">If it is wrong, change your words above and read them again. Nothing is signed until you confirm.</p>
          </div>
        )}
        {mandate && (
          <div className="result ok">
            <h3>Instruction signed</h3>
            <p>Limit {money(mandate.limit)} per purchase. Stores: {mandate.vendors.join(", ")}. Items: {mandate.categories.map(c => CAT[c] ?? c).join(", ") || "any"}.</p>
          </div>
        )}
      </div>
      {mandate && (
        <div className="form">
          <label>Store<input value={vendor} onChange={e => setVendor(e.target.value)} /></label>
          <label>Item<input value={title} onChange={e => setTitle(e.target.value)} /></label>
          <label>Price in dollars<input type="number" min="0.01" step="0.01" value={price} onChange={e => setPrice(e.target.value)} /></label>
          {live
            ? <button className="btn primary inline" disabled={busy} onClick={buy}>Check, then buy in the PayPal sandbox</button>
            : <button className="btn primary inline" disabled={busy} onClick={demoCheck}>Check this cart</button>}
        </div>
      )}
      {!live && <p className="subtle" style={{ marginTop: 14 }}>This check never reaches PayPal. Add your PayPal sandbox keys to <code>.env</code> to let the agent buy for real.</p>}
      {err && <p className="error">{err}</p>}
      {order && (
        <div className="result ok">
          <h3>Allowed. Waiting for the buyer to pay.</h3>
          <p>Approve the payment in PayPal's sandbox with your buyer account, then come back and finish.</p>
          <p><a href={order.approve_url} target="_blank" rel="noreferrer">Open PayPal to approve</a></p>
          <button className="btn" disabled={busy} onClick={finish}>I approved it. Finish the purchase</button>
        </div>
      )}
      {done && (
        <div className="result ok">
          <h3>Bought. The agent signed a receipt.</h3>
          <p>PayPal payment {done.capture_id}. If the buyer now reports a problem on this payment in PayPal's sandbox, load that dispute in the Merchant console and Warrant will find this receipt.</p>
        </div>
      )}
      {res && (
        <div className={"result " + (res.status === "allow" ? "ok" : "bad")}>
          <h3>{CHECK_TEXT[res.status]}</h3>
          <p>{res.explanation}</p>
          {res.item_reads.length > 0 && <div style={{ marginTop: 6 }}><Reading items={res.item_reads} /></div>}
          <p className="subtle">{res.codes.map(c => REASON[c] ?? c.toLowerCase().replaceAll("_", " ")).join(", ")}{res.codes.length ? ". " : ""}Nothing was sent to PayPal.</p>
        </div>
      )}
    </div>
  );
}

const readSource = (r: Understood) => r.source.startsWith("fixed") ? `Read by the ${r.source}.` : `Read by ${r.source}.`;
const readError = (e: unknown) => {
  const m = String(e).replace(/^Error: \d+ /, "");
  try { const j = JSON.parse(m); return typeof j.detail === "string" ? j.detail : "Check what you typed. The price must be above zero and the text must be short enough."; } catch { return m; }
};

function CheckPacket({ openId }: { openId: string | null }) {
  const [text, setText] = useState("");
  const [res, setRes] = useState<Verified | null>(null);
  const [err, setErr] = useState("");
  const fill = async () => { if (openId) { setText(await api.packet(openId)); setRes(null); setErr(""); } };
  const check = async () => {
    setErr(""); setRes(null);
    try { setRes(await api.verifyPacket(JSON.parse(text))); } catch (e) { setErr(e instanceof SyntaxError ? "That is not valid JSON." : String(e)); }
  };
  const word = (v: string) => (v === "valid" || v === "ok" ? "passes" : v === "broken" ? "fails because the file was changed" : v === "unknown keys" ? "fails because the key is not one Warrant knows" : v);
  return (
    <div className="page">
      <h2>Check an evidence packet</h2>
      <p>A packet carries the signed instruction and receipt. Paste one to see whether it has been changed. Edit one word of the ruling and check again.</p>
      <div className="form">
        {openId && <button className="btn inline" onClick={fill}>Use the packet for {openId}</button>}
        <textarea className="mono-block" rows={9} placeholder="Paste a packet here" value={text} onChange={e => setText(e.target.value)} aria-label="Evidence packet" />
        <button className="btn primary inline" disabled={!text.trim()} onClick={check}>Check this packet</button>
      </div>
      {err && <p className="error">{err}</p>}
      {res && (
        <div className={"result " + (res.ok ? "ok" : "bad")}>
          <h3>{res.ok ? "Nothing has been changed." : "This packet cannot be trusted."}</h3>
          <p>File fingerprint {word(res.hash)}. The buyer's instruction signature {word(res.mandate_signature)}. The agent's receipt signature {word(res.receipt_signature)}.</p>
        </div>
      )}
    </div>
  );
}

function LoadLive({ onLoaded }: { onLoaded: (id: string) => void }) {
  const [id, setId] = useState("");
  const [rec, setRec] = useState("delivered");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const go = async () => {
    setBusy(true); setErr("");
    try { const r = await api.liveLoad(id.trim(), rec); onLoaded(r.dispute_id); setId(""); }
    catch (e) { setErr(String(e).replace(/^Error: \d+ /, "")); } finally { setBusy(false); }
  };
  return (
    <div className="loadlive">
      <h3>Load a real sandbox dispute</h3>
      <div className="row">
        <input placeholder="PP-R-XXX-12345678" value={id} onChange={e => setId(e.target.value)} aria-label="PayPal dispute id" />
        <select value={rec} onChange={e => setRec(e.target.value)} aria-label="What your store recorded" style={{ width: "auto" }}>
          <option value="delivered">Store says delivered</option>
          <option value="not_delivered">Store says not delivered</option>
          <option value="unknown">Store has no record</option>
        </select>
        <button className="btn primary" disabled={busy || !id.trim()} onClick={go}>Load from PayPal</button>
      </div>
      {err && <p className="error">{err}</p>}
    </div>
  );
}

type View = "merchant" | "buyer" | "packet" | "agent";
type Role = "owner" | "buyer" | "dev";
const ROLES: [Role, string][] = [["owner", "Store owner"], ["buyer", "Buyer"], ["dev", "Developer"]];
const ROLE_VIEWS: Record<Role, View[]> = { owner: ["merchant"], buyer: ["agent", "buyer"], dev: ["packet"] };
const ROLE_LEDE: Record<Role, string> = {
  owner: "Disputes filed against your store. Warrant recommends. PayPal decides.",
  buyer: "Tell your agent what it may buy, then see how a dispute turns out. Warrant recommends. PayPal decides.",
  dev: "Check an evidence packet for edits. The packet spec is in docs/spec and the scenarios are in data/scenarios.",
};
const savedRole = (): Role => { try { const r = localStorage.getItem("role"); if (r === "owner" || r === "buyer" || r === "dev") return r; } catch {} return "owner"; };

export default function App() {
  const [rows, setRows] = useState<Row[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [role, setRole] = useState<Role>(savedRole);
  const [view, setView] = useState<View>(() => ROLE_VIEWS[savedRole()][0]);
  const [err, setErr] = useState("");
  const [live, setLive] = useState(false);
  const [find, setFind] = useState("");
  const pickRole = (r: Role) => { setRole(r); setView(ROLE_VIEWS[r][0]); try { localStorage.setItem("role", r); } catch {} };
  useEffect(() => { api.liveStatus().then(r => setLive(r.enabled)).catch(() => {}); }, []);

  const load = useCallback(async () => {
    try {
      const q = await api.queue(); setRows(q);
      const id = sel ?? q[0]?.dispute_id ?? null; setSel(id);
      if (id) setDetail(await api.detail(id));
    } catch (e) { setErr(String(e)); }
  }, [sel]);
  useEffect(() => { load(); }, [load]);

  const [narrow, setNarrow] = useState(window.innerWidth < 760);
  useEffect(() => { const f = () => setNarrow(window.innerWidth < 760); window.addEventListener("resize", f); return () => window.removeEventListener("resize", f); }, []);
  const allCols = useMemo<ColDef<Row>[]>(() => [
    { field: "dispute_id", headerName: "Dispute", width: 140,
      cellRenderer: (p: any) => <span>{String(p.value).replace("PP-R-", "")}</span> },
    { field: "verdict", headerName: "Ruling", width: 180, filter: true, filterValueGetter: p => VERDICT[p.data?.verdict as Verdict]?.name ?? "", getQuickFilterText: p => VERDICT[p.data?.verdict as Verdict]?.name ?? "",
      cellRenderer: (p: any) => <span className={"ruling " + VERDICT[p.value as Verdict].cls}><i />{VERDICT[p.value as Verdict].name}</span> },
    { field: "action", headerName: "Recommends", flex: 1, minWidth: 140, valueFormatter: p => SHORT[p.value as string] ?? p.value },
    { field: "days_left", headerName: "Due in", width: 96, sort: "asc", valueFormatter: p => (p.value === null ? "Not set" : p.value >= 1 ? `${Math.floor(p.value)} d` : `${Math.round(p.value * 24)} h`),
      cellClass: p => (p.value !== null && p.value < 3 ? "cell-urgent" : "") },
    { field: "state", headerName: "Status", width: 132, filter: true, filterValueGetter: p => STATE_TEXT[p.data?.state as Row["state"]] ?? "", getQuickFilterText: p => STATE_TEXT[p.data?.state as Row["state"]] ?? "", valueFormatter: p => STATE_TEXT[p.value as Row["state"]],
      cellClass: p => (p.value === "pending" ? "status-open" : "status-done") },
  ], []);
  // On a phone the docket keeps the columns that decide what to open: dispute, ruling, time left.
  const cols = useMemo(() => role === "buyer" && !narrow
    ? allCols.filter(c => ["dispute_id", "verdict", "days_left"].includes(String(c.field))).map(c => c.field === "verdict" ? { ...c, width: undefined, flex: 1 } : c)
    : narrow
    ? allCols.filter(c => ["dispute_id", "verdict", "days_left"].includes(String(c.field))).map(c => c.field === "dispute_id"
        ? { ...c, width: 96 }
        : c.field === "verdict" ? { ...c, width: undefined, flex: 1, minWidth: 160 } : { ...c, width: 66, headerName: "Due" })
    : allCols, [allCols, narrow, role]);

  const pending = rows.filter(r => r.state === "pending").length;
  const names: Record<View, string> = { merchant: "Disputes", buyer: "Your dispute", packet: "Check a packet", agent: live ? "Buyer's agent" : "Try a purchase" };
  const tabs: [View, string][] = ROLE_VIEWS[role].map(k => [k, names[k]]);
  const showQueue = view === "merchant" || view === "buyer";
  return (
    <div className="shell">
      <header>
        <div className="bar">
          <h1 className="brand"><Mark /><span>Warrant</span></h1>
          <div className="roles" role="radiogroup" aria-label="Viewing as" title="Demo roles, not accounts">
            <span>Viewing as</span>
            {ROLES.map(([k, label]) => <button key={k} role="radio" aria-checked={role === k} onClick={() => pickRole(k)}>{label}</button>)}
          </div>
        </div>
        {tabs.length > 1 && (
          <div className="tabs" role="tablist" aria-label="Views">
            {tabs.map(([k, label]) => <button key={k} role="tab" aria-selected={view === k} onClick={() => setView(k)}>{label}</button>)}
          </div>
        )}
        <hr className="rule" />
        <p className="lede">{ROLE_LEDE[role]}</p>
        <p className="roles-note">Demo roles. Switching shows each person’s screens. There are no accounts.</p>
      </header>
      {err && <p className="error">Cannot reach the Warrant API. Start it with <code>uvicorn warrant.api:app</code>. ({err})</p>}
      <main>
        {showQueue && <div className="queue">
          {live && view === "merchant" && <LoadLive onLoaded={id => { setSel(id); api.queue().then(setRows); api.detail(id).then(setDetail); }} />}
          <div className="panel-head"><h2>Disputes</h2><span>{role === "buyer" ? `${rows.length} disputes` : `${pending} waiting for you`}</span></div>
          {rows.length > 0 && <p className="source-note">{rows.every(r => r.source === "live") ? "Live: real PayPal sandbox disputes. Approving sends the action to PayPal." : "Recorded: real PayPal sandbox disputes from our own run. Approving here sends nothing."}</p>}
          <input className="find" type="search" placeholder="Search disputes by ruling, status or number" aria-label="Search disputes" value={find} onChange={e => setFind(e.target.value)} />
          <div className="ag-theme-quartz warrant-grid">
            <AgGridReact<Row> domLayout="autoHeight" quickFilterText={find} rowData={rows} columnDefs={cols} rowSelection={{ mode: "singleRow", checkboxes: false, enableClickSelection: true }} getRowId={p => p.data.dispute_id}
              onRowClicked={e => { if (e.data) { setSel(e.data.dispute_id); api.detail(e.data.dispute_id).then(setDetail); } }}
              rowClassRules={{ "row-sel": p => p.data?.dispute_id === sel }} />
          </div>
          {view === "merchant" && (
            <div className="legend">
              <h3>How Warrant rules</h3>
              <dl>
                {(Object.keys(VERDICT) as Verdict[]).map(k => (
                  <Fragment key={k}><dt><span className={"ruling " + VERDICT[k].cls}><i />{VERDICT[k].name}</span></dt><dd>{LEGEND[k]}</dd></Fragment>
                ))}
              </dl>
            </div>
          )}
        </div>}
        <aside className={showQueue ? "" : "solo"}>
          {view === "packet" ? <CheckPacket openId={sel} /> : view === "agent" ? <BuyerAgent live={live} /> : detail && sel && (view === "merchant" ? <Merchant d={detail} onChange={load} /> : <BuyerView id={sel} />)}
        </aside>
      </main>
    </div>
  );
}

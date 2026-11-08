export const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "";

export type Row = {
  source: "live" | "recorded"; paypal_status: { status?: string; dispute_state?: string; dispute_life_cycle_stage?: string } | null;
  dispute_id: string; amount: string; currency: string; reason: string; buyer_said: string;
  verdict: Verdict; codes: string[]; explanation: string; action: string; action_text: string;
  days_left: number | null; due: string | null; state: "pending" | "approved" | "overridden";
};
export type Verdict = "WITHIN_MANDATE" | "OVERSTEPPED" | "MERCHANT_FAULT" | "UNRESOLVED";
export type Audit = { ts: number; actor: string; verdict: string; action: string; executed: number; note: string };
export type ItemRead = { item: string; category: string; confidence: number; source: string };
export type Detail = Row & {
  item_reads: ItemRead[];
  audit: Audit[]; data_note: string; fulfilment: Record<string, unknown>;
  mandate: { instruction?: string; limit?: number; vendors?: string[]; categories?: string[]; signature: string } | null;
  receipt: { vendor?: string; items?: { title: string; price_cents: number; qty: number }[]; total?: number; told_buyer?: string; why?: string; untrusted_inputs?: string[]; signature: string } | null;
};
export type Buyer = { you_allowed: string | null; agent_did: Detail["receipt"]; plain: string; reasons: string; verdict: Verdict; state: Row["state"] };

async function call<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(BASE + path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : undefined);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}
export type Check = { status: "allow" | "block" | "ask_human"; codes: string[]; explanation: string; mandate: string; reached_paypal: boolean; item_reads: ItemRead[] };
export type MandateView = { mandate_id: string; instruction: string; limit: number; vendors: string[]; categories: string[]; window_cap: number | null; valid_until: number; signature_preview: string };
export type Understood = { limit: number; vendors: string[]; categories: string[]; window_cap: number | null; window_hours: number; valid_days: number; source: string; model_used: boolean };
export type Purchase = { status: string; codes?: string[]; explanation?: string; order_id?: string; approve_url?: string; item_reads?: ItemRead[]; capture_id?: string; receipt_id?: string };
export type Verified = { ok: boolean; hash: string; mandate_signature: string; receipt_signature: string; matches_stated_checks: boolean | null };
export const api = {
  packet: async (id: string) => JSON.stringify(await (await fetch(BASE + `/api/disputes/${id}/packet`)).json(), null, 1),
  verifyPacket: (packet: unknown) => call<Verified>("/api/packets/verify", packet),
  liveStatus: () => call<{ enabled: boolean }>("/api/live/status"),
  readInstruction: (instruction: string) => call<Understood>("/api/instruction/read", { instruction }),
  mandate: (instruction: string, fields: Understood) => call<MandateView>("/api/mandates", { instruction, fields }),
  livePurchase: (b: { mandate_id: string; title: string; price: number; vendor: string }) => call<Purchase>("/api/live/purchases", b),
  liveFinish: (order_id: string) => call<Purchase>(`/api/live/purchases/${order_id}/finish`, {}),
  liveLoad: (dispute_id: string, delivery: string) => call<Row>("/api/live/disputes", { dispute_id, delivery }),
  preflight: (b: { vendor: string; title: string; price: number; mandate_id?: string }) => call<Check>("/api/preflight", b),
  queue: () => call<Row[]>("/api/disputes"),
  detail: (id: string) => call<Detail>(`/api/disputes/${id}`),
  buyer: (id: string) => call<Buyer>(`/api/buyer/${id}`),
  approve: (id: string, actor: string) => call<Row>(`/api/disputes/${id}/approve`, { actor }),
  override: (id: string, actor: string, action: string, note: string) => call<Row>(`/api/disputes/${id}/override`, { actor, action, note }),
};

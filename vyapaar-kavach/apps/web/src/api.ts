const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined) || "http://127.0.0.1:8000";

export class ApiError extends Error {
  status: number;
  code: string | null;
  retryable: boolean;

  constructor(status: number, code: string | null, message: string, retryable = false) {
    super(message);
    this.status = status;
    this.code = code;
    this.retryable = retryable;
  }
}

type UnauthorizedHandler = () => void;
let onUnauthorized: UnauthorizedHandler | null = null;
export function setUnauthorizedHandler(handler: UnauthorizedHandler) {
  onUnauthorized = handler;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      credentials: "include",
      headers: { "Content-Type": "application/json", ...(options.headers ?? {}) },
      ...options,
    });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "Could not reach the API server.");
  }

  if (res.status === 401) {
    if (onUnauthorized) onUnauthorized();
    throw new ApiError(401, "UNAUTHORIZED", "You are not signed in.");
  }

  const text = await res.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }

  if (!res.ok) {
    let code: string | null = null;
    let message = `Request failed (${res.status})`;
    let retryable = false;
    if (body && typeof body === "object") {
      const detail = (body as Record<string, unknown>).detail;
      if (detail && typeof detail === "object") {
        const d = detail as Record<string, unknown>;
        if (typeof d.code === "string") code = d.code;
        if (typeof d.error === "string") message = d.error;
        else if (code) message = code;
        if (typeof d.retryable === "boolean") retryable = d.retryable;
      } else if (typeof detail === "string") {
        message = detail;
      }
    }
    throw new ApiError(res.status, code, message, retryable);
  }

  return body as T;
}

export async function getJson<T>(path: string): Promise<T> {
  return request<T>(path);
}

export async function getText(path: string): Promise<string> {
  const res = await fetch(`${API_BASE}${path}`, { credentials: "include" });
  if (res.status === 401) {
    if (onUnauthorized) onUnauthorized();
    throw new ApiError(401, "UNAUTHORIZED", "You are not signed in.");
  }
  const text = await res.text();
  if (!res.ok) {
    throw new ApiError(res.status, null, `Request failed (${res.status})`);
  }
  return text;
}

export async function postJson<TReq, TRes>(path: string, payload: TReq): Promise<TRes> {
  return request<TRes>(path, { method: "POST", body: JSON.stringify(payload) });
}

// ---------- Types ----------

export interface Membership {
  tenant_id: string;
  tenant_name: string;
  role: string;
}

export interface MeResponse {
  user_id: string;
  username: string;
  display_name: string;
  tenant_id: string;
  role: string;
  memberships: Membership[];
  environment: string;
}

export interface PaymentSummary {
  id: string;
  order_ref: string;
  provider_txn_id: string;
  amount_paise: number;
  currency: string;
  status: string;
  verification: string;
  last_checked_at: string | null;
  customer_hint: string | null;
}

export interface RefundOut {
  id: string;
  refund_ref: string;
  amount_paise: number;
  currency: string;
  status: string;
  origin: string;
  last_checked_at: string | null;
}

export interface PaymentDetail extends PaymentSummary {
  refunds: RefundOut[];
}

export interface RefreshResponse {
  payment: PaymentSummary;
  refunds: RefundOut[];
}

export interface CaseOut {
  id: string;
  claim_type: string;
  claimed_amount_paise: number | null;
  reference_text: string | null;
  status: string;
  match_status: string;
  payment_id: string | null;
  created_at: string;
  created_by: string;
  version: number;
  resolution_text: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
}

export interface CandidateOut {
  payment_id: string;
  order_ref: string;
  provider_txn_id: string;
  amount_paise: number;
  currency: string;
  status: string;
  created_at: string;
  reason: string;
}

export interface TimelineItem {
  at: string;
  kind: string;
  source_kind: string;
  label: string;
  detail: string;
  verification_status: string | null;
}

export interface Recommendation {
  case_id: string;
  policy_version: string;
  action: string;
  reason_codes: string[];
  summary: string;
  supporting_observation_ids: string[];
  missing_facts: string[];
  provider_last_checked_at: string | null;
  model_used_for_action: boolean;
  execution_allowed: boolean;
}

export interface ExportResult {
  export_id: string;
  sha256: string;
}

export interface DemoControlResult {
  ok: boolean;
  effect?: string;
  [key: string]: unknown;
}

export interface RunSummaryExample {
  graph_index: number;
  prob_suspicious: number;
  label: number;
}

export interface RunSummary {
  model_version: string;
  threshold: number;
  sample_size: number;
  positives: number;
  metrics: { precision: number; recall: number; f1: number };
  device: string;
  runtime_ms: number;
  examples: RunSummaryExample[];
  note: string;
}

export interface RunOut {
  id: string;
  task: string;
  data_mode: string;
  model_version: string;
  abstained: boolean;
  abstention_reason: string | null;
  runtime_ms: number;
  created_at: string;
  checkpoint_sha256: string;
  dataset_sha256: string;
  summary?: RunSummary;
}

// ---------- Endpoints ----------

export const api = {
  login: (username: string, password: string) =>
    postJson<{ username: string; password: string }, MeResponse>("/v1/auth/login", {
      username,
      password,
    }),
  logout: () => request<unknown>("/v1/auth/logout", { method: "POST" }),
  me: () => getJson<MeResponse>("/v1/me"),
  payments: (q: string) =>
    getJson<PaymentSummary[]>(`/v1/payments?q=${encodeURIComponent(q)}`),
  payment: (id: string) => getJson<PaymentDetail>(`/v1/payments/${id}`),
  refreshPayment: (id: string) =>
    postJson<Record<string, never>, RefreshResponse>(`/v1/payments/${id}/refresh`, {}),
  cases: (status?: string) =>
    getJson<CaseOut[]>(`/v1/cases${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  createCase: (payload: {
    claim_type: string;
    claimed_amount_paise?: number | null;
    reference?: string;
    note?: string;
  }) => postJson<typeof payload, CaseOut>("/v1/cases", payload),
  case: (id: string) => getJson<CaseOut>(`/v1/cases/${id}`),
  matchCandidates: (id: string) => getJson<CandidateOut[]>(`/v1/cases/${id}/match-candidates`),
  matchCase: (id: string, paymentId: string) =>
    postJson<{ payment_id: string }, CaseOut>(`/v1/cases/${id}/match`, {
      payment_id: paymentId,
    }),
  timeline: (id: string) => getJson<TimelineItem[]>(`/v1/cases/${id}/timeline`),
  recommendation: (id: string) => getJson<Recommendation>(`/v1/cases/${id}/recommendation`),
  addNote: (id: string, text: string) =>
    postJson<{ text: string }, { id: string }>(`/v1/cases/${id}/notes`, { text }),
  resolveCase: (id: string, resolution: string, caseVersion: number) =>
    postJson<{ resolution: string; case_version: number }, CaseOut>(
      `/v1/cases/${id}/resolve`,
      { resolution, case_version: caseVersion }
    ),
  createExport: (id: string) =>
    postJson<Record<string, never>, ExportResult>(`/v1/cases/${id}/exports`, {}),
  exportText: (exportId: string, format: "md" | "json") =>
    getText(`/v1/exports/${exportId}?format=${format}`),
  researchRuns: () => getJson<RunOut[]>("/v1/research/runs"),
  researchRun: (id: string) => getJson<RunOut>(`/v1/research/runs/${id}`),
  runResearch: (task: string, sampleSize: number) =>
    postJson<{ task: string; sample_size: number }, RunOut>("/v1/research/runs", {
      task,
      sample_size: sampleSize,
    }),
  demoControl: (scenario: string) =>
    postJson<{ scenario: string }, DemoControlResult>("/v1/demo/controls", { scenario }),
};

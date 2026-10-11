export type Verdict = "ALLOW" | "BLOCK" | "ESCALATE";
export type Status = "allowed" | "blocked" | "pending" | "approved" | "rejected" | "expired" | "handed_off";
export type Mode = "live" | "off" | "error";

export interface JevSignals {
  p_safe: number;
  p_on_task: number;
  risk: string;
  risk_probabilities: Record<string, number>;
  risk_confidence: number;
  severity: number;
  severity_confidence: number;
  severity_probabilities: Record<string, number>;
  output_ok: number | null;
  confidence: number;
}

export interface JevResult {
  model: string;
  latency_ms: number;
  signals: JevSignals;
  answers: Record<string, unknown>;
  state: Record<string, unknown>;
}

export interface TraceSpan {
  name: string;
  kind?: string;
  model?: string;
  duration_ms?: number;
  children?: TraceSpan[];
}

export interface TraceRef {
  mode: Mode;
  trace_id: string | null;
  url: string | null;
  payload: TraceSpan & Record<string, unknown>;
  error: string | null;
}

export interface Decision {
  id: string;
  created_at: number;
  agent_name: string;
  session_id: string | null;
  tool: string;
  args: Record<string, unknown>;
  context: {
    task: string | null;
    reasoning: string | null;
    history: Record<string, unknown>[];
    entire_session_id: string | null;
    metadata: Record<string, unknown>;
  };
  verdict: Verdict;
  status: Status;
  confidence: number;
  reasons: string[];
  jev: JevResult | null;
  jev_error: string | null;
  latency_ms: number;
  explanation: { text: string; model: string; generated_at: number } | null;
  explanation_pending: boolean;
  explanation_error: string | null;
  entire: Record<string, unknown> | null;
  trace: TraceRef | null;
  result: { ok: boolean; output: string | null; error: string | null } | null;
  resolved_by: string | null;
  resolved_at: number | null;
  note: string | null;
}

export interface Thresholds {
  block_safe_below: number;
  allow_safe_above: number;
  min_confidence: number;
  severity_escalate: number;
  severity_block: number;
  risk_block: number;
  on_task_min: number;
  output_ok_min: number;
}

export type Integration = "jev" | "neatlogs" | "entire" | "explainer";

export interface Health {
  modes: Record<Integration, Mode>;
  thresholds: Thresholds;
  llm_model: string;
  jev_model: string;
  jev_base_url: string;
  neatlogs_project: string;
  neatlogs_app_url: string;
  escalation_timeout_s: number;
}

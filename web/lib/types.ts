// Trace records streamed by agent/ui.py (one per line of a run's trace.jsonl, plus start/done/error/warming).

export type Driver = "llm" | "jev" | "cascade";

export interface Usage {
  input_tokens?: number;
  output_tokens?: number;
  cache_creation_input_tokens?: number;
  cache_read_input_tokens?: number;
}

export interface Candidate {
  cmd: string;
  p: number;
  seen?: boolean;
}

export interface RunResult {
  driver: Driver;
  model: string;
  app: string;
  run_dir: string;
  wall_s: number;
  cache?: boolean;
  claude_turns: number;
  claude_s: number;
  input_tokens: number;
  output_tokens: number;
  input_equiv_tokens?: number;
  cache_read_tokens?: number;
  cache_write_tokens?: number;
  tool_calls: number;
  tool_s: number;
  jev_calls: number;
  jev_errors: number;
  jev_commits: number;
  jev_declined: number;
  jev_s: number;
  jev_cost_usd?: number;
  threshold?: number;
  pages_fetched: string[];
  pages_named: string[];
  answer_chars: number;
  small_model?: string | null;
  per_model?: Record<string, { turns: number; input_tokens: number; output_tokens: number; input_equiv_tokens?: number }>;
}

interface Base {
  t: number;
  side?: Driver;
}

export type TraceEvent =
  | (Base & { kind: "warming"; app: string })
  | (Base & { kind: "start"; driver: Driver; model: string; app: string; task: string; small_model?: string | null; threshold?: number; cache?: boolean })
  | (Base & { kind: "claude" | "small"; turn: number; seconds: number; stop?: string; tool_uses: number; text?: string; usage?: Usage; model?: string })
  | (Base & { kind: "tool"; who: "claude" | "jev" | "small"; tool: string; args: Record<string, unknown>; seconds: number; chars?: number; error?: boolean })
  | (Base & { kind: "jev"; p_call_tool: number; top: string | null; p_top: number; n_candidates: number; latency: number; route?: string; cost_usd?: number | null; top5?: Candidate[]; threshold?: number })
  | (Base & { kind: "commit"; p: number; key: string })
  | (Base & { kind: "jev_error"; error: string })
  | (Base & { kind: "escalate"; turn: number; discarded_chars?: number })
  | (Base & { kind: "error"; error: string })
  | (Base & { kind: "done"; result: RunResult; answer: string });

export interface RunSummary {
  name: string;
  driver: Driver;
  app: string;
  wall_s: number;
  turns: number;
  tools: number;
  input_tokens: number;
  cache?: boolean;
  threshold?: number;
  pages_named: number;
  stamp: string;
}

export interface SavedRun {
  name: string;
  events: TraceEvent[];
  result: RunResult;
  answer: string;
}

export interface Config {
  apps: Record<string, { prompt: string; server: string }>;
  drivers: Driver[];
  model: string;
  small_model: string;
  have_anthropic_key: boolean;
  have_jev_key: boolean;
  runs_dir: string;
}

// ---- what the page renders ----

export type Item =
  | { type: "note"; text: string; detail?: string; t?: number; tone?: "grey" | "bad" }
  | { type: "turn"; who: "claude" | "small"; turn: number; seconds: number; text: string; toolUses: number; t: number }
  | { type: "tool"; who: string; tool: string; args: Record<string, unknown>; seconds: number; chars: number; error: boolean }
  | { type: "jev"; latency: number; pCall: number; threshold: number; candidates: Candidate[]; status: "pending" | "committed" | "declined"; commitP?: number; declinedTo?: string; t: number };

export interface SideState {
  driver: Driver;
  label: string;
  model?: string;
  turns: number;
  tools: number;
  tokens: number;
  jevCalls: number;
  jevCommits: number;
  jevCost: number;
  clock: number; // seconds shown on the wall counter
  items: Item[];
  done: boolean;
  result?: RunResult;
  answer?: string;
}

export const LABEL: Record<Driver, string> = { llm: "Claude alone", jev: "Claude + Jev", cascade: "Haiku cascade" };

export const API = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8765";

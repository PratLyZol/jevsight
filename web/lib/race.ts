// Claude Code races: plain Claude Code vs Claude Code with the Jevsight proxy, from race/race.py run directories.

export type RaceSide = "baseline" | "jevsight";

export interface RaceCandidate {
  cmd: string;
  p: number;
  ev?: number | null;
  decision?: string;
}

export type RaceEvent =
  | { kind: "start"; t: number; side: RaceSide; task: string }
  | { kind: "narration"; t: number; text: string }
  | { kind: "call"; t: number; id: string; tool: string; args: Record<string, unknown>; key: string }
  | { kind: "result"; t: number; id: string; tool: string; wait: number; chars: number; error: boolean; served?: "hit" | "miss" | null; head_start?: number | null }
  | { kind: "other_tool"; t: number; tool: string }
  | { kind: "predict"; t: number; latency: number; p_run: number; n_candidates: number; after_narration?: boolean; top: RaceCandidate[] }
  | { kind: "launch"; t: number; cmd: string; p: number; ev?: number }
  | { kind: "job_done"; t: number; cmd: string; dur: number; status: string }
  | { kind: "hit"; t: number; cmd: string; head_start?: number | null; p?: number }
  | { kind: "miss"; t: number; cmd: string }
  | { kind: "predict_error"; t: number; error: string }
  | { kind: "done"; t: number; num_turns: number; cost_usd: number; input_tokens: number; output_tokens: number; answer: string; mcp_calls: number; wait_s: number; hits: number };

export interface RaceSummary {
  name: string;
  app: string;
  running?: boolean;
  predictor: string;
  jev_errors: number | null;
  baseline: { seconds: number | null; mcp_calls: number | null; wait_s: number | null };
  jevsight: { seconds: number | null; mcp_calls: number | null; wait_s: number | null; hits?: number | null };
}

export interface SavedRace {
  name: string;
  task: string;
  running?: boolean;
  sides: Record<RaceSide, RaceEvent[]>;
}

export type RaceItem =
  | { type: "note"; text: string; detail?: string; t?: number; tone?: "grey" | "bad" }
  | { type: "narration"; text: string; t: number }
  | { type: "call"; id: string; tool: string; args: Record<string, unknown>; t: number; wait?: number; chars?: number; error?: boolean; served?: "hit" | "miss" | null; headStart?: number | null; pending: boolean }
  | { type: "predict"; t: number; latency: number; pRun: number; n: number; afterNarration: boolean; top: RaceCandidate[] }
  | { type: "early"; t: number; cmd: string; p: number; dur?: number; status?: string };

export interface RaceSideState {
  side: RaceSide;
  label: string;
  clock: number;
  turns: number;
  calls: number;
  waited: number;
  hits: number;
  launches: number;
  jevCalls: number;
  items: RaceItem[];
  done: boolean;
  result?: Extract<RaceEvent, { kind: "done" }>;
}

export const RACE_LABEL: Record<RaceSide, string> = { baseline: "Claude Code", jevsight: "Claude Code + Jevsight proxy" };

export function emptyRaceSide(side: RaceSide): RaceSideState {
  return { side, label: RACE_LABEL[side], clock: 0, turns: 0, calls: 0, waited: 0, hits: 0, launches: 0, jevCalls: 0, items: [], done: false };
}

export function reduceRace(s: RaceSideState, ev: RaceEvent): RaceSideState {
  switch (ev.kind) {
    case "start":
      return { ...s, items: [...s.items, { type: "note", text: "Task", detail: ev.task, t: 0 }] };
    case "narration":
      return { ...s, items: [...s.items, { type: "narration", text: ev.text, t: ev.t }] };
    case "call":
      return { ...s, calls: s.calls + 1, items: [...s.items, { type: "call", id: ev.id, tool: ev.tool, args: ev.args, t: ev.t, pending: true }] };
    case "result": {
      const items = s.items.slice();
      const idx = items.findIndex((x) => x.type === "call" && x.id === ev.id);
      if (idx >= 0) {
        const c = items[idx];
        if (c.type === "call") items[idx] = { ...c, pending: false, wait: ev.wait, chars: ev.chars, error: ev.error, served: ev.served ?? null, headStart: ev.head_start ?? null };
      }
      return { ...s, waited: s.waited + ev.wait, hits: s.hits + (ev.served === "hit" ? 1 : 0), items };
    }
    case "predict":
      return { ...s, jevCalls: s.jevCalls + 1, items: [...s.items, { type: "predict", t: ev.t, latency: ev.latency, pRun: ev.p_run, n: ev.n_candidates, afterNarration: !!ev.after_narration, top: ev.top }] };
    case "launch":
      return { ...s, launches: s.launches + 1, items: [...s.items, { type: "early", t: ev.t, cmd: ev.cmd, p: ev.p }] };
    case "job_done": {
      const items = s.items.slice();
      for (let i = items.length - 1; i >= 0; i--) {
        const x = items[i];
        if (x.type === "early" && x.cmd === ev.cmd && x.dur == null) {
          items[i] = { ...x, dur: ev.dur, status: ev.status };
          break;
        }
      }
      return { ...s, items };
    }
    case "predict_error":
      return { ...s, jevCalls: s.jevCalls + 1, items: [...s.items, { type: "note", text: "Jev unavailable, call relayed as usual", detail: ev.error, t: ev.t }] };
    case "done":
      return { ...s, done: true, clock: ev.t, turns: ev.num_turns, calls: ev.mcp_calls, waited: ev.wait_s, hits: ev.hits, result: ev };
    default:
      return s;
  }
}

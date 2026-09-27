// A plain Claude Code session on the same task (recorded by race/race.py --only baseline), for the versus view.

export type CcEvent =
  | { kind: "start"; t: number; task: string }
  | { kind: "narration"; t: number; text: string }
  | { kind: "call"; t: number; id: string; tool: string; args: Record<string, unknown> }
  | { kind: "result"; t: number; id: string; tool: string; wait: number; chars: number; error: boolean }
  | { kind: "done"; t: number; num_turns: number; cost_usd: number; input_tokens: number; output_tokens: number; answer: string };

export interface CcSummary {
  name: string;
  app: string;
  running: boolean;
  seconds: number | null;
  turns: number | null;
  calls: number;
  cost_usd: number | null;
  task: string;
}

export interface SavedCc {
  name: string;
  task: string;
  running: boolean;
  events: CcEvent[];
}

export type CcItem =
  | { type: "note"; text: string; detail?: string; t?: number }
  | { type: "narration"; text: string; t: number }
  | { type: "call"; id: string; tool: string; args: Record<string, unknown>; t: number; wait?: number; chars?: number; error?: boolean; pending: boolean };

export interface CcState {
  label: string;
  clock: number;
  turns: number;
  calls: number;
  waited: number;
  items: CcItem[];
  done: boolean;
  result?: Extract<CcEvent, { kind: "done" }>;
}

export function emptyCc(): CcState {
  return { label: "Claude Code", clock: 0, turns: 0, calls: 0, waited: 0, items: [], done: false };
}

export function reduceCc(s: CcState, ev: CcEvent): CcState {
  switch (ev.kind) {
    case "start":
      return { ...s, items: [...s.items, { type: "note", text: "Task", detail: ev.task, t: 0 }] };
    case "narration":
      return { ...s, turns: s.done ? s.turns : s.turns + 1, items: [...s.items, { type: "narration", text: ev.text, t: ev.t }] };
    case "call":
      return { ...s, calls: s.calls + 1, items: [...s.items, { type: "call", id: ev.id, tool: ev.tool, args: ev.args, t: ev.t, pending: true }] };
    case "result": {
      const items = s.items.slice();
      const i = items.findIndex((x) => x.type === "call" && x.id === ev.id);
      if (i >= 0) {
        const c = items[i];
        if (c.type === "call") items[i] = { ...c, pending: false, wait: ev.wait, chars: ev.chars, error: ev.error };
      }
      return { ...s, waited: s.waited + ev.wait, items };
    }
    case "done":
      return { ...s, done: true, clock: ev.t, turns: ev.num_turns, result: ev };
    default:
      return s;
  }
}

export function ccFromEvents(events: CcEvent[]): CcState {
  let s = emptyCc();
  for (const e of events) s = reduceCc(s, e);
  return s;
}

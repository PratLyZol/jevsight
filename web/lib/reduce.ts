import { Driver, Item, LABEL, SideState, TraceEvent } from "./types";

export function emptySide(driver: Driver): SideState {
  return { driver, label: LABEL[driver], turns: 0, tools: 0, tokens: 0, jevCalls: 0, jevCommits: 0, jevCost: 0, clock: 0, items: [], done: false };
}

/** Compact one-line form of a call key such as `fetch {"url":"https://…/asyncio-task.html","max_length":40000}`. */
export function shortCmd(key: string): string {
  const i = key.indexOf(" ");
  const name = i < 0 ? key : key.slice(0, i);
  let args: Record<string, unknown> = {};
  try {
    args = JSON.parse(key.slice(i + 1)) as Record<string, unknown>;
  } catch {
    /* not json: show as is */
  }
  const parts: string[] = [];
  for (const [k, v] of Object.entries(args)) {
    if (k === "url" && typeof v === "string") parts.push(v.replace(/^https?:\/\/[^/]+\//, "…/").slice(-48));
    else parts.push(`${k}=${String(v).slice(0, 24)}`);
  }
  return `${name} ${parts.join(" ")}`;
}

export function fmt(n: number | undefined): string {
  if (n == null) return "–";
  return n >= 1000 ? (n / 1000).toFixed(n >= 100000 ? 0 : 1) + "k" : String(n);
}

function settlePendingJev(items: Item[], to: string): Item[] {
  const idx = items.map((x) => x.type).lastIndexOf("jev");
  if (idx < 0) return items;
  const j = items[idx];
  if (j.type !== "jev" || j.status !== "pending") return items;
  const copy = items.slice();
  copy[idx] = { ...j, status: "declined", declinedTo: to };
  return copy;
}

/** Apply one trace event to one side's state. Pure, so replay and live use the same code. */
export function reduce(s: SideState, ev: TraceEvent): SideState {
  switch (ev.kind) {
    case "warming":
      return { ...s, items: [...s.items, { type: "note", text: `Starting the ${ev.app} tool server…` }] };
    case "start":
      return {
        ...s,
        model: `${ev.model}${ev.small_model ? " + " + ev.small_model : ""}${ev.cache ? " · cached" : ""}${ev.driver !== "llm" && ev.threshold != null ? " · threshold " + ev.threshold : ""}`,
        items: [...s.items, { type: "note", text: "Task", detail: ev.task, t: 0 }],
      };
    case "claude":
    case "small": {
      const u = ev.usage ?? {};
      const tokens = (u.input_tokens ?? 0) + (u.cache_creation_input_tokens ?? 0) + (u.cache_read_input_tokens ?? 0);
      const items = settlePendingJev(s.items, ev.kind === "small" ? "Haiku" : "Claude");
      return {
        ...s,
        turns: s.turns + 1,
        tokens: s.tokens + tokens,
        items: [...items, { type: "turn", who: ev.kind, turn: ev.turn, seconds: ev.seconds, text: ev.text ?? "", toolUses: ev.tool_uses, t: ev.t }],
      };
    }
    case "tool":
      return { ...s, tools: s.tools + 1, items: [...s.items, { type: "tool", who: ev.who, tool: ev.tool, args: ev.args, seconds: ev.seconds, chars: ev.chars ?? 0, error: !!ev.error }] };
    case "jev": {
      const candidates = ev.top5 && ev.top5.length ? ev.top5 : ev.top ? [{ cmd: ev.top, p: ev.p_top }] : [];
      return {
        ...s,
        jevCalls: s.jevCalls + 1,
        jevCost: s.jevCost + (ev.cost_usd ?? 0),
        items: [...s.items, { type: "jev", latency: ev.latency, pCall: ev.p_call_tool, threshold: ev.threshold ?? 0.4, candidates, status: "pending", t: ev.t }],
      };
    }
    case "commit": {
      const idx = s.items.map((x) => x.type).lastIndexOf("jev");
      const items = s.items.slice();
      const j = items[idx];
      if (j && j.type === "jev") items[idx] = { ...j, status: "committed", commitP: ev.p };
      return { ...s, jevCommits: s.jevCommits + 1, items };
    }
    case "jev_error":
      return { ...s, items: [...s.items, { type: "note", text: "Jev unavailable → Claude takes the turn", detail: ev.error, t: ev.t }] };
    case "escalate":
      return { ...s, items: [...s.items, { type: "note", text: `Navigation done after ${ev.turn} Haiku turns → Opus writes the answer`, t: ev.t }] };
    case "error":
      return { ...s, done: true, items: [...s.items, { type: "note", text: "Run failed", detail: ev.error, tone: "bad" }] };
    case "done":
      return {
        ...s,
        done: true,
        clock: ev.result.wall_s,
        turns: ev.result.claude_turns,
        tools: ev.result.tool_calls,
        tokens: ev.result.input_tokens,
        jevCalls: ev.result.jev_calls || s.jevCalls,
        jevCommits: ev.result.jev_commits || s.jevCommits,
        jevCost: ev.result.jev_cost_usd ?? s.jevCost,
        result: ev.result,
        answer: ev.answer,
      };
    default:
      return s;
  }
}

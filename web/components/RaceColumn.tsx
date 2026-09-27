"use client";

import { useEffect, useRef } from "react";
import { fmt, shortCmd } from "@/lib/reduce";
import type { RaceItem, RaceSideState } from "@/lib/race";

const WAIT_FULL = 2.5; // seconds of waiting that fills the bar

function Item({ item }: { item: RaceItem }) {
  switch (item.type) {
    case "note":
      return (
        <div className={`card ${item.tone ?? "grey"}`}>
          <div className="head">
            <span>{item.text}</span>
            {item.t != null && <span className="t">t+{item.t.toFixed(1)}s</span>}
          </div>
          {item.detail && <div className="body">{item.detail}</div>}
        </div>
      );
    case "narration":
      return (
        <div className="card claude">
          <div className="head">
            <span>Claude says</span>
            <span className="t">t+{item.t.toFixed(1)}s</span>
          </div>
          <div className="body">{item.text}</div>
        </div>
      );
    case "call": {
      const label = item.pending
        ? "waiting…"
        : item.served === "hit"
          ? `served in ${(item.wait ?? 0).toFixed(2)}s · ran ${(item.headStart ?? 0).toFixed(1)}s early`
          : `${(item.wait ?? 0).toFixed(2)}s`;
      const width = Math.min(100, Math.round(((item.wait ?? 0) / WAIT_FULL) * 100));
      return (
        <div className={`call${item.served === "hit" ? " hit" : ""}${item.pending ? " pending" : ""}`}>
          <div className="line">
            <span className="args">{shortCmd(`${item.tool} ${JSON.stringify(item.args)}`)}</span>
            <span className="t">
              {label}
              {item.chars != null ? ` · ${fmt(item.chars)} chars` : ""}
              {item.error ? " · error" : ""}
            </span>
          </div>
          <div className="wait">
            <i style={{ width: `${item.pending ? 100 : width}%` }} />
          </div>
        </div>
      );
    }
    case "predict":
      return (
        <div className="card jev">
          <div className="head">
            <span>
              Jev · {item.latency.toFixed(2)}s · P(another call) {item.pRun.toFixed(2)} · {item.n} candidates{item.afterNarration ? " · after Claude's words" : ""}
            </span>
            <span className="t">t+{item.t.toFixed(1)}s</span>
          </div>
          <div className="cands">
            {item.top.map((c, i) => (
              <div className={`cand${i === 0 ? " top" : ""}`} key={c.cmd + i}>
                <span>{c.p.toFixed(2)}</span>
                <div className="bar">
                  <i style={{ width: `${Math.round(c.p * 100)}%` }} />
                  <em>{shortCmd(c.cmd)}</em>
                </div>
                <span className={`decision ${c.decision ?? "skip"}`}>{c.decision === "launch" ? `run early · EV +${(c.ev ?? 0).toFixed(2)}` : c.decision === "have" ? "already running" : "skip"}</span>
              </div>
            ))}
          </div>
        </div>
      );
    case "early":
      return (
        <div className="call early">
          <div className="line">
            <span className="args">running early · {shortCmd(item.cmd)}</span>
            <span className="t">{item.dur != null ? `done in ${item.dur.toFixed(2)}s` : "in flight…"}</span>
          </div>
        </div>
      );
  }
}

export default function RaceColumn({ side }: { side: RaceSideState }) {
  const listRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [side.items.length]);
  const r = side.result;
  return (
    <section className={`col ${side.side}`}>
      <h3>
        <span>{side.label}</span>
      </h3>
      <div className="stats">
        <div className="stat">
          <b>{side.clock.toFixed(1)}s</b>
          <span>wall</span>
        </div>
        <div className="stat">
          <b>{side.turns || "–"}</b>
          <span>turns</span>
        </div>
        <div className="stat">
          <b>{side.calls}</b>
          <span>tool calls</span>
        </div>
        <div className="stat">
          <b>{side.waited.toFixed(1)}s</b>
          <span>waited on tools</span>
        </div>
        <div className="stat">
          <b>{side.side === "jevsight" ? `${side.hits}/${side.calls}` : "–"}</b>
          <span>answered early</span>
        </div>
      </div>
      <div className="cards" ref={listRef}>
        {side.items.map((it, i) => (
          <Item item={it} key={i} />
        ))}
      </div>
      {r && (
        <div className="answer">
          <h4>
            Answer · {r.num_turns} turns · ${r.cost_usd.toFixed(2)} · {fmt(r.input_tokens)} input tokens
          </h4>
          <pre>{r.answer}</pre>
        </div>
      )}
    </section>
  );
}

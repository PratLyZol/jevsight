"use client";

import { useEffect, useRef } from "react";
import { fmt, shortCmd } from "@/lib/reduce";
import type { Item, SideState } from "@/lib/types";

function ItemView({ item }: { item: Item }) {
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
    case "turn": {
      const who = item.who === "small" ? "Haiku" : "Claude";
      const what = item.toolUses ? `${item.toolUses} tool call${item.toolUses > 1 ? "s" : ""}` : "writes the answer";
      return (
        <div className={`card ${item.who}`}>
          <div className="head">
            <span>
              {who} · turn {item.turn} · {item.seconds.toFixed(1)}s → {what}
            </span>
            <span className="t">t+{item.t.toFixed(1)}s</span>
          </div>
          {item.text && <div className="body">{item.text}</div>}
        </div>
      );
    }
    case "tool":
      return (
        <div className="tool">
          <span className={`who ${item.who}`}>{item.who}</span>
          <span className="args">{shortCmd(`${item.tool} ${JSON.stringify(item.args)}`)}</span>
          <span className="t">
            {item.seconds.toFixed(2)}s · {fmt(item.chars)} chars{item.error ? " · ERROR" : ""}
          </span>
        </div>
      );
    case "jev": {
      const tag =
        item.status === "committed" ? `committed at p ${(item.commitP ?? 0).toFixed(2)}` : item.status === "declined" ? `declined → ${item.declinedTo ?? "Claude"}` : "deciding";
      return (
        <div className="card jev">
          <div className="head">
            <span>
              Jev · {item.latency.toFixed(2)}s · P(another call) {item.pCall.toFixed(2)}
            </span>
            <span className={`tag ${item.status}`}>{tag}</span>
            <span className="t">t+{item.t.toFixed(1)}s</span>
          </div>
          <div className="cands">
            {item.candidates.map((c, i) => (
              <div className={`cand${i === 0 ? " top" : ""}`} key={c.cmd}>
                <span>{c.p.toFixed(2)}</span>
                <div className="bar">
                  <i style={{ width: `${Math.round(c.p * 100)}%` }} />
                  <b className="th" style={{ left: `${Math.round(item.threshold * 100)}%` }} />
                  <em>
                    {shortCmd(c.cmd)}
                    {c.seen ? "  (already called)" : ""}
                  </em>
                </div>
              </div>
            ))}
          </div>
        </div>
      );
    }
  }
}

export default function RunColumn({ side }: { side: SideState }) {
  const listRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [side.items.length]);
  const r = side.result;
  return (
    <section className="col">
      <h3>
        <span>{side.label}</span>
        <span className="model">{side.model ?? ""}</span>
      </h3>
      <div className="stats">
        <div className="stat">
          <b>{side.clock.toFixed(1)}s</b>
          <span>wall</span>
        </div>
        <div className="stat">
          <b>{side.turns}</b>
          <span>model turns</span>
        </div>
        <div className="stat">
          <b>{side.tools}</b>
          <span>tool calls</span>
        </div>
        <div className="stat">
          <b>
            {fmt(side.tokens)}
            {r?.cache && r.input_equiv_tokens != null ? ` · ${fmt(r.input_equiv_tokens)} billed` : ""}
          </b>
          <span>input tokens</span>
        </div>
        <div className="stat">
          <b>{side.driver === "jev" ? `${side.jevCommits}/${side.jevCalls} · ${(side.jevCost * 100).toFixed(2)}¢` : "–"}</b>
          <span>jev turns · cost</span>
        </div>
      </div>
      <div className="cards" ref={listRef}>
        {side.items.map((it, i) => (
          <ItemView item={it} key={i} />
        ))}
      </div>
      {r && (
        <div className="answer">
          <h4>Answer</h4>
          <div className="chips">
            {r.pages_fetched.map((p) => (
              <span className={`chip${r.pages_named.includes(p) ? " ok" : ""}`} key={p}>
                {p}
              </span>
            ))}
          </div>
          <pre>{side.answer}</pre>
        </div>
      )}
    </section>
  );
}

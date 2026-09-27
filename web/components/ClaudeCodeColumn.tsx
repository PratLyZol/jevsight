"use client";

import { useEffect, useRef } from "react";
import { fmt, shortCmd } from "@/lib/reduce";
import type { CcItem, CcState } from "@/lib/cc";

const WAIT_FULL = 2.5; // seconds of waiting that fills the bar

function Item({ item }: { item: CcItem }) {
  switch (item.type) {
    case "note":
      return (
        <div className="card grey">
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
            <span>Claude Code says</span>
            <span className="t">t+{item.t.toFixed(1)}s</span>
          </div>
          <div className="body">{item.text}</div>
        </div>
      );
    case "call": {
      const width = Math.min(100, Math.round(((item.wait ?? 0) / WAIT_FULL) * 100));
      return (
        <div className={`call${item.pending ? " pending" : ""}`}>
          <div className="line">
            <span className="args">{shortCmd(`${item.tool} ${JSON.stringify(item.args)}`)}</span>
            <span className="t">
              {item.pending ? "waiting…" : `${(item.wait ?? 0).toFixed(2)}s`}
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
  }
}

export default function ClaudeCodeColumn({ side }: { side: CcState }) {
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
        <span className="model">the real CLI, clean config, same model and MCP server</span>
      </h3>
      <div className="stats">
        <div className="stat">
          <b>{side.clock.toFixed(1)}s</b>
          <span>wall</span>
        </div>
        <div className="stat">
          <b>{side.turns || "–"}</b>
          <span>model turns</span>
        </div>
        <div className="stat">
          <b>{side.calls}</b>
          <span>tool calls</span>
        </div>
        <div className="stat">
          <b>{r ? fmt(r.input_tokens) : "–"}</b>
          <span>input tokens</span>
        </div>
        <div className="stat">
          <b>{r?.cost_usd != null ? `$${r.cost_usd.toFixed(2)}` : "–"}</b>
          <span>billed</span>
        </div>
      </div>
      <div className="cards" ref={listRef}>
        {side.items.map((it, i) => (
          <Item item={it} key={i} />
        ))}
      </div>
      {r && (
        <div className="answer">
          <h4>Answer</h4>
          <pre>{r.answer}</pre>
        </div>
      )}
    </section>
  );
}

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ClaudeCodeColumn from "@/components/ClaudeCodeColumn";
import Compare from "@/components/Compare";
import RunColumn from "@/components/RunColumn";
import { ccFromEvents, emptyCc, reduceCc, type CcEvent, type CcState, type CcSummary, type SavedCc } from "@/lib/cc";
import { emptySide, fmt, reduce } from "@/lib/reduce";
import { API, type Config, type Driver, LABEL, type RunSummary, type SavedRun, type SideState, type TraceEvent } from "@/lib/types";

type Mode = Driver | "both" | "versus";
const ORDER: Driver[] = ["llm", "cascade", "jev"];
const SPEEDS = [1, 2, 4, 10];
const MODES: [Mode, string][] = [
  ["versus", "Claude Code vs Claude + Jev"],
  ["jev", LABEL.jev],
  ["llm", LABEL.llm],
  ["both", "Claude alone vs Claude + Jev"],
  ["cascade", LABEL.cascade],
];

type Tagged = (TraceEvent & { src: "loop" }) | (CcEvent & { src: "cc" });

export default function Page() {
  const [config, setConfig] = useState<Config | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [ccRuns, setCcRuns] = useState<CcSummary[]>([]);
  const [task, setTask] = useState("");
  const [app, setApp] = useState("fetch");
  const [threshold, setThreshold] = useState(0.4);
  const [mode, setMode] = useState<Mode>("versus");
  const [speed, setSpeed] = useState(4);
  const [picked, setPicked] = useState<string[]>([]);
  const [pickedCc, setPickedCc] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [sides, setSides] = useState<SideState[]>([]);
  const [cc, setCc] = useState<CcState | null>(null);

  const source = useRef<EventSource | null>(null);
  const timer = useRef<number | null>(null);
  const pump = useRef<number | null>(null);
  const poll = useRef<number | null>(null);
  const clockStart = useRef<Record<string, number>>({});

  const loadRuns = useCallback(async () => {
    setRuns((await (await fetch(`${API}/api/runs`)).json()) as RunSummary[]);
    setCcRuns((await (await fetch(`${API}/api/ccruns`)).json()) as CcSummary[]);
  }, []);

  useEffect(() => {
    (async () => {
      const c = (await (await fetch(`${API}/api/config`)).json()) as Config;
      setConfig(c);
      setTask(c.apps[app]?.prompt ?? "");
      await loadRuns();
    })().catch((e) => setStatus(`The API is not running. Start it with python3 agent/ui.py (${e})`));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const stopAll = () => {
    source.current?.close();
    source.current = null;
    for (const r of [timer, pump, poll]) {
      if (r.current) window.clearInterval(r.current);
      r.current = null;
    }
  };

  const startClock = (simulated?: () => number) => {
    if (timer.current) window.clearInterval(timer.current);
    timer.current = window.setInterval(() => {
      const tick = <T extends { done: boolean; clock: number }>(s: T, key: string): T => {
        if (s.done) return s;
        if (simulated) return { ...s, clock: simulated() };
        const t0 = clockStart.current[key];
        return t0 == null ? s : { ...s, clock: (performance.now() - t0) / 1000 };
      };
      setSides((prev) => prev.map((s) => tick(s, s.driver)));
      setCc((prev) => (prev ? tick(prev, "cc") : prev));
    }, 100);
  };

  const applyLoop = (ev: TraceEvent) => setSides((prev) => prev.map((s) => (s.driver === ev.side ? reduce(s, ev) : s)));

  function listenLoop(job: string, onEnd: () => void) {
    const es = new EventSource(`${API}/api/events?job=${job}`);
    source.current = es;
    es.onmessage = (e) => {
      const ev = JSON.parse(e.data) as TraceEvent;
      if (ev.kind === "start" && ev.side) clockStart.current[ev.side] = performance.now();
      applyLoop(ev);
    };
    es.addEventListener("end", () => {
      es.close();
      source.current = null;
      onEnd();
    });
    es.onerror = () => setStatus("The event stream closed");
  }

  // ---- live: agent loop only ----
  async function startLive() {
    if (mode === "versus") return startVersus();
    const drivers: Driver[] = mode === "both" ? ["llm", "jev"] : [mode];
    stopAll();
    clockStart.current = {};
    setCc(null);
    setSides(drivers.map(emptySide));
    setBusy(true);
    setStatus("Starting…");
    const r = (await (
      await fetch(`${API}/api/run`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ task, app, drivers, threshold }) })
    ).json()) as { job?: string; error?: string };
    if (!r.job) {
      setStatus(r.error ?? "Could not start the run");
      setBusy(false);
      return;
    }
    setStatus(`Running (job ${r.job})`);
    listenLoop(r.job, () => {
      stopAll();
      setBusy(false);
      setStatus("Finished");
      loadRuns();
    });
    startClock();
  }

  // ---- live: plain Claude Code (race.py --only baseline) next to Claude + Jev, started together ----
  async function startVersus() {
    stopAll();
    clockStart.current = {};
    setSides([emptySide("jev")]);
    setCc(emptyCc());
    setBusy(true);
    setStatus("Starting Claude Code and the agent…");
    const r = (await (
      await fetch(`${API}/api/versus`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ task, app, threshold }) })
    ).json()) as { cc?: string; job?: string; error?: string };
    if (!r.cc || !r.job) {
      setStatus(r.error ?? "Could not start");
      setBusy(false);
      return;
    }
    const name = r.cc;
    clockStart.current.cc = performance.now();
    let loopDone = false;
    let ccDone = false;
    const finish = () => {
      if (loopDone && ccDone) {
        stopAll();
        setBusy(false);
        setStatus("Finished");
        loadRuns();
      }
    };
    listenLoop(r.job, () => {
      loopDone = true;
      finish();
    });
    const refresh = async () => {
      const saved = (await (await fetch(`${API}/api/cc?name=${encodeURIComponent(name)}`)).json()) as SavedCc;
      const s = ccFromEvents(saved.events);
      setCc((prev) => (s.done ? s : { ...s, clock: prev?.clock ?? 0 }));
      if (!saved.running && s.done) {
        ccDone = true;
        if (poll.current) window.clearInterval(poll.current);
        poll.current = null;
        finish();
      }
    };
    setStatus(`Racing (${name})`);
    poll.current = window.setInterval(refresh, 2000);
    startClock();
  }

  // ---- replay ----
  function playback(evs: Tagged[], rate: number) {
    const start = performance.now();
    const now = () => ((performance.now() - start) / 1000) * rate;
    let i = 0;
    startClock(now);
    pump.current = window.setInterval(() => {
      const t = now();
      while (i < evs.length && (evs[i].t ?? 0) <= t) {
        const ev = evs[i++];
        if (ev.src === "cc") setCc((prev) => (prev ? reduceCc(prev, ev) : prev));
        else applyLoop(ev);
      }
      if (i >= evs.length) {
        stopAll();
        setStatus("Replay finished");
      }
    }, 50);
  }

  async function startReplay(which?: string[], ccName?: string, atSpeed?: number) {
    const names = (which ?? picked).slice(0, 2);
    const ccPick = ccName ?? (mode === "versus" ? pickedCc : "");
    const rate = atSpeed ?? speed;
    if (!names.length && !ccPick) return;
    const loaded = (await Promise.all(names.map((n) => fetch(`${API}/api/run?name=${encodeURIComponent(n)}`).then((r) => r.json())))) as SavedRun[];
    loaded.sort((x, y) => ORDER.indexOf(x.result.driver) - ORDER.indexOf(y.result.driver));
    const drivers = loaded.map((r) => r.result.driver);
    if (new Set(drivers).size < drivers.length) {
      setStatus("Pick two runs with different drivers");
      return;
    }
    const savedCc = ccPick ? ((await (await fetch(`${API}/api/cc?name=${encodeURIComponent(ccPick)}`)).json()) as SavedCc) : null;
    stopAll();
    setSides(drivers.map(emptySide));
    setCc(savedCc ? emptyCc() : null);
    const evs: Tagged[] = [];
    for (const r of loaded) for (const e of r.events) evs.push({ ...e, side: r.result.driver, src: "loop" });
    if (savedCc) for (const e of savedCc.events) evs.push({ ...e, src: "cc" });
    evs.sort((x, y) => (x.t ?? 0) - (y.t ?? 0));
    playback(evs, rate);
    setStatus(`Replaying ${[ccPick, ...names].filter(Boolean).join(" and ")} at ${rate}×`);
  }

  // deep links for demos: /?replay=<run>,<run>&speed=4   or   /?versus=<race>,<run>&speed=4
  const autoplayed = useRef(false);
  useEffect(() => {
    if (autoplayed.current || !runs.length) return;
    const q = new URLSearchParams(window.location.search);
    const rate = parseFloat(q.get("speed") ?? "") || speed;
    const replay = (q.get("replay") ?? "").split(",").filter(Boolean);
    const versus = (q.get("versus") ?? "").split(",").filter(Boolean);
    if (!replay.length && versus.length < 2) return;
    autoplayed.current = true;
    setSpeed(rate);
    if (versus.length >= 2) {
      setMode("versus");
      setPickedCc(versus[0]);
      setPicked([versus[1]]);
      startReplay([versus[1]], versus[0], rate);
    } else {
      setPicked(replay);
      startReplay(replay, "", rate);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runs]);

  const loopJev = sides.find((s) => s.driver === "jev");
  const pct = (x: number, y: number) => `${(100 * (y - x) / x).toFixed(0)}%`;

  return (
    <>
      <div className="topbar">
        <div className="wordmark">
          <i /> Jevsight
        </div>
        <span className="keys">{config ? `${config.model} · Anthropic key ${config.have_anthropic_key ? "on" : "missing"} · Jev key ${config.have_jev_key ? "on" : "missing"}` : "connecting to the API…"}</span>
      </div>

      <main>
        <section className="hero">
          <div>
            <h1>Let the frontier model think. Let Jev click the links.</h1>
            <p className="lede">
              {mode === "versus"
                ? "Plain Claude Code on the left, the Claude + Jev agent on the right. Same task, same model, same tool server, started together."
                : "Give the agent a read-only research task. Watch which turns Claude takes and which ones Jev takes for it."}
            </p>
            <textarea value={task} onChange={(e) => setTask(e.target.value)} placeholder="Describe a read-only research task…" />
            <div className="row">
              <label>Tool server</label>
              <select
                value={app}
                onChange={(e) => {
                  setApp(e.target.value);
                  setTask(config?.apps[e.target.value]?.prompt ?? "");
                }}
              >
                {config &&
                  Object.entries(config.apps).map(([k, v]) => (
                    <option value={k} key={k}>
                      {k} ({v.server})
                    </option>
                  ))}
              </select>
              <button className="btn ghost" onClick={() => setTask(config?.apps[app]?.prompt ?? "")}>
                Use the benchmark task
              </button>
              <label>Jev commits at</label>
              <input type="number" value={threshold} min={0.1} max={0.95} step={0.05} style={{ width: 84 }} onChange={(e) => setThreshold(parseFloat(e.target.value))} />
            </div>
            <div className="row">
              <div className="segment" role="radiogroup">
                {MODES.map(([m, l]) => (
                  <button key={m} role="radio" aria-checked={mode === m} className={mode === m ? "active" : ""} onClick={() => setMode(m)}>
                    {l}
                  </button>
                ))}
              </div>
              <button className="btn primary" onClick={startLive} disabled={busy || !config?.have_anthropic_key}>
                {mode === "versus" ? "Start both" : "Run the agent"}
              </button>
            </div>
            <div className="status">{status}</div>
          </div>
          <div className="side-panel">
            <h2>Replay a saved run</h2>
            {mode === "versus" ? (
              <>
                <p>A recorded Claude Code session on the left, a recorded agent run on the right. Pick one of each; the 14-page pair is the long one.</p>
                <select value={pickedCc} onChange={(e) => setPickedCc(e.target.value)} style={{ width: "100%", fontFamily: "var(--font-mono)", fontSize: 12, marginBottom: 8 }}>
                  <option value="">Claude Code session…</option>
                  {ccRuns.map((r) => (
                    <option value={r.name} key={r.name}>
                      {r.name.slice(5)} {r.app.padEnd(10)} {r.running ? "running" : `${r.seconds}s ${r.turns} turns ${r.calls} calls $${(r.cost_usd ?? 0).toFixed(2)}`}
                    </option>
                  ))}
                </select>
                <select value={picked[0] ?? ""} onChange={(e) => setPicked([e.target.value])} style={{ width: "100%", fontFamily: "var(--font-mono)", fontSize: 12 }}>
                  <option value="">Agent run…</option>
                  {runs
                    .filter((r) => r.driver === "jev")
                    .map((r) => (
                      <option value={r.name} key={r.name}>
                        {r.stamp} {r.app.padEnd(10)} {r.wall_s}s {r.turns} turns {r.tools} calls {Math.round(r.input_tokens / 1000)}k
                      </option>
                    ))}
                </select>
              </>
            ) : (
              <>
                <p>Pick one run, or two with different drivers for a side-by-side replay. Real timings, only faster.</p>
                <select className="runs" multiple value={picked} onChange={(e) => setPicked([...e.target.selectedOptions].map((o) => o.value))}>
                  {runs.map((r) => (
                    <option value={r.name} key={r.name}>
                      {r.stamp} {r.driver.padEnd(7)} {r.app.padEnd(10)} {String(r.wall_s).padStart(6)}s {String(r.turns).padStart(2)} turns {String(r.tools).padStart(2)} calls{" "}
                      {Math.round(r.input_tokens / 1000)}k{r.cache ? " cached" : ""}
                    </option>
                  ))}
                </select>
              </>
            )}
            <div className="row">
              <label>Speed</label>
              <select value={speed} onChange={(e) => setSpeed(parseFloat(e.target.value))}>
                {SPEEDS.map((s) => (
                  <option value={s} key={s}>
                    {s}×
                  </option>
                ))}
              </select>
              <button className="btn primary" onClick={() => startReplay()} disabled={busy}>
                Play
              </button>
              <button className="btn ghost" onClick={loadRuns}>
                Refresh
              </button>
            </div>
          </div>
        </section>

        {mode === "versus" && cc?.result && loopJev?.result ? (
          <div className="compare">
            <div className="tile">
              <b>{pct(cc.result.t, loopJev.result.wall_s)}</b>
              <span>
                wall · Claude Code {cc.result.t.toFixed(1)}s → agent {loopJev.result.wall_s}s
              </span>
            </div>
            <div className="tile">
              <b>{pct(cc.result.num_turns, loopJev.result.claude_turns)}</b>
              <span>
                frontier-model turns · {cc.result.num_turns} → {loopJev.result.claude_turns}
              </span>
            </div>
            <div className="tile">
              <b>
                {cc.calls} vs {loopJev.result.tool_calls}
              </b>
              <span>tool calls · Jev took {loopJev.result.jev_commits} of them</span>
            </div>
            <div className="tile">
              <b>{pct(cc.result.input_tokens, loopJev.result.input_tokens)}</b>
              <span>
                input tokens read · {fmt(cc.result.input_tokens)} → {fmt(loopJev.result.input_tokens)}
              </span>
            </div>
          </div>
        ) : (
          <Compare sides={sides} />
        )}

        <div className={`columns${sides.length + (cc ? 1 : 0) === 2 ? " two" : ""}`}>
          {cc && <ClaudeCodeColumn side={cc} />}
          {sides.map((s) => (
            <RunColumn side={s} key={s.driver} />
          ))}
        </div>
        {mode === "versus" && (
          <p className="hint" style={{ marginTop: 12 }}>
            Different harnesses: Claude Code has its own system prompt, tool plumbing and caching. Same model, same prompt, same MCP server, same moment.
          </p>
        )}
      </main>
    </>
  );
}

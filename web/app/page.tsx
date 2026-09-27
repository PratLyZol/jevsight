"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Compare from "@/components/Compare";
import RunColumn from "@/components/RunColumn";
import { emptySide, reduce } from "@/lib/reduce";
import { API, type Config, type Driver, LABEL, type RunSummary, type SavedRun, type SideState, type TraceEvent } from "@/lib/types";

type Mode = Driver | "both";
const ORDER: Driver[] = ["llm", "cascade", "jev"];
const SPEEDS = [1, 2, 4, 10];

export default function Page() {
  const [config, setConfig] = useState<Config | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [task, setTask] = useState("");
  const [app, setApp] = useState("fetch");
  const [threshold, setThreshold] = useState(0.4);
  const [mode, setMode] = useState<Mode>("jev");
  const [speed, setSpeed] = useState(4);
  const [picked, setPicked] = useState<string[]>([]);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [sides, setSides] = useState<SideState[]>([]);

  const source = useRef<EventSource | null>(null);
  const timer = useRef<number | null>(null);
  const pump = useRef<number | null>(null);
  const clockStart = useRef<Record<string, number>>({});

  const loadRuns = useCallback(async () => {
    setRuns((await (await fetch(`${API}/api/runs`)).json()) as RunSummary[]);
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
    if (timer.current) window.clearInterval(timer.current);
    if (pump.current) window.clearInterval(pump.current);
    timer.current = pump.current = null;
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
    }, 100);
  };

  // ---- agent loop: live ----
  async function startLive() {
    const drivers: Driver[] = mode === "both" ? ["llm", "jev"] : [mode];
    stopAll();
    clockStart.current = {};
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
    const es = new EventSource(`${API}/api/events?job=${r.job}`);
    source.current = es;
    es.onmessage = (e) => {
      const ev = JSON.parse(e.data) as TraceEvent;
      if (ev.kind === "start" && ev.side) clockStart.current[ev.side] = performance.now();
      setSides((prev) => prev.map((s) => (s.driver === ev.side ? reduce(s, ev) : s)));
    };
    es.addEventListener("end", () => {
      stopAll();
      setBusy(false);
      setStatus("Finished");
      loadRuns();
    });
    es.onerror = () => {
      setStatus("The event stream closed");
      setBusy(false);
    };
    startClock();
  }

  // ---- agent loop: replay ----
  async function startReplay(which?: string[], atSpeed?: number) {
    const names = (which ?? picked).slice(0, 2);
    const rate = atSpeed ?? speed;
    if (!names.length) return;
    const loaded = (await Promise.all(names.map((n) => fetch(`${API}/api/run?name=${encodeURIComponent(n)}`).then((r) => r.json())))) as SavedRun[];
    loaded.sort((x, y) => ORDER.indexOf(x.result.driver) - ORDER.indexOf(y.result.driver));
    const drivers = loaded.map((r) => r.result.driver);
    if (new Set(drivers).size < drivers.length) {
      setStatus("Pick two runs with different drivers");
      return;
    }
    stopAll();
    setSides(drivers.map(emptySide));
    const evs: TraceEvent[] = [];
    for (const r of loaded) for (const e of r.events) evs.push({ ...e, side: r.result.driver });
    evs.sort((x, y) => (x.t ?? 0) - (y.t ?? 0));
    playback(evs, rate, (ev) => setSides((prev) => prev.map((s) => (s.driver === ev.side ? reduce(s, ev) : s))));
    setStatus(`Replaying ${names.join(" and ")} at ${rate}×`);
  }

  function playback<E extends { t?: number }>(evs: E[], rate: number, apply: (ev: E) => void) {
    const start = performance.now();
    const now = () => ((performance.now() - start) / 1000) * rate;
    let i = 0;
    startClock(now);
    pump.current = window.setInterval(() => {
      const t = now();
      while (i < evs.length && (evs[i].t ?? 0) <= t) apply(evs[i++]);
      if (i >= evs.length) {
        stopAll();
        setStatus("Replay finished");
      }
    }, 50);
  }

  // deep links for demos: /?replay=<run>,<run>&speed=4  or  /?race=<race>&speed=4
  const autoplayed = useRef(false);
  useEffect(() => {
    if (autoplayed.current || !runs.length) return;
    const q = new URLSearchParams(window.location.search);
    const rate = parseFloat(q.get("speed") ?? "") || speed;
    const replay = (q.get("replay") ?? "").split(",").filter(Boolean);
    if (!replay.length) return;
    autoplayed.current = true;
    setSpeed(rate);
    setPicked(replay);
    startReplay(replay, rate);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runs]);

  const modes: [Mode, string][] = [
    ["jev", LABEL.jev],
    ["llm", LABEL.llm],
    ["both", "Side by side"],
    ["cascade", LABEL.cascade],
  ];

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
              <p className="lede">Give the agent a read-only research task. Watch which turns Claude takes and which ones Jev takes for it.</p>
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
                  {modes.map(([m, l]) => (
                    <button key={m} role="radio" aria-checked={mode === m} className={mode === m ? "active" : ""} onClick={() => setMode(m)}>
                      {l}
                    </button>
                  ))}
                </div>
                <button className="btn primary" onClick={startLive} disabled={busy || !config?.have_anthropic_key}>
                  Run the agent
                </button>
              </div>
              <div className="status">{status}</div>
            </div>
            <div className="side-panel">
              <h2>Replay a saved run</h2>
              <p>Pick one run, or two with different drivers for a side-by-side replay. Real timings, only faster.</p>
              <select className="runs" multiple value={picked} onChange={(e) => setPicked([...e.target.selectedOptions].map((o) => o.value))}>
                {runs.map((r) => (
                  <option value={r.name} key={r.name}>
                    {r.stamp} {r.driver.padEnd(7)} {r.app.padEnd(6)} {String(r.wall_s).padStart(6)}s {String(r.turns).padStart(2)} turns {String(r.tools).padStart(2)} calls {Math.round(r.input_tokens / 1000)}k
                    {r.cache ? " cached" : ""}
                  </option>
                ))}
              </select>
              <div className="row">
                <label>Speed</label>
                <select value={speed} onChange={(e) => setSpeed(parseFloat(e.target.value))}>
                  {SPEEDS.map((s) => (
                    <option value={s} key={s}>
                      {s}×
                    </option>
                  ))}
                </select>
                <button className="btn primary" onClick={() => startReplay()}>
                  Play
                </button>
                <button className="btn ghost" onClick={loadRuns}>
                  Refresh
                </button>
              </div>
            </div>
        </section>

        <Compare sides={sides} />
        <div className={`columns${sides.length === 2 ? " two" : ""}`}>
          {sides.map((s) => (
            <RunColumn side={s} key={s.driver} />
          ))}
        </div>
      </main>
    </>
  );
}

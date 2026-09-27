"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Compare from "@/components/Compare";
import RaceColumn from "@/components/RaceColumn";
import RunColumn from "@/components/RunColumn";
import { emptyRaceSide, reduceRace, type RaceEvent, type RaceSide, type RaceSideState, type RaceSummary, type SavedRace } from "@/lib/race";
import { emptySide, reduce } from "@/lib/reduce";
import { API, type Config, type Driver, LABEL, type RunSummary, type SavedRun, type SideState, type TraceEvent } from "@/lib/types";

type Mode = Driver | "both";
type Tab = "loop" | "race";
const ORDER: Driver[] = ["llm", "cascade", "jev"];
const SPEEDS = [1, 2, 4, 10];

export default function Page() {
  const [tab, setTab] = useState<Tab>("loop");
  const [config, setConfig] = useState<Config | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [races, setRaces] = useState<RaceSummary[]>([]);
  const [task, setTask] = useState("");
  const [app, setApp] = useState("fetch");
  const [threshold, setThreshold] = useState(0.4);
  const [mode, setMode] = useState<Mode>("jev");
  const [speed, setSpeed] = useState(4);
  const [picked, setPicked] = useState<string[]>([]);
  const [pickedRace, setPickedRace] = useState("");
  const [raceApp, setRaceApp] = useState("fetch");
  const poll = useRef<number | null>(null);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [sides, setSides] = useState<SideState[]>([]);
  const [raceSides, setRaceSides] = useState<RaceSideState[]>([]);

  const source = useRef<EventSource | null>(null);
  const timer = useRef<number | null>(null);
  const pump = useRef<number | null>(null);
  const clockStart = useRef<Record<string, number>>({});

  const loadRuns = useCallback(async () => {
    setRuns((await (await fetch(`${API}/api/runs`)).json()) as RunSummary[]);
    setRaces((await (await fetch(`${API}/api/races`)).json()) as RaceSummary[]);
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
    if (poll.current) window.clearInterval(poll.current);
    timer.current = pump.current = poll.current = null;
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
      setRaceSides((prev) => prev.map((s) => tick(s, s.side)));
    }, 100);
  };

  // ---- agent loop: live ----
  async function startLive() {
    const drivers: Driver[] = mode === "both" ? ["llm", "jev"] : [mode];
    stopAll();
    clockStart.current = {};
    setRaceSides([]);
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
    setRaceSides([]);
    setSides(drivers.map(emptySide));
    const evs: TraceEvent[] = [];
    for (const r of loaded) for (const e of r.events) evs.push({ ...e, side: r.result.driver });
    evs.sort((x, y) => (x.t ?? 0) - (y.t ?? 0));
    playback(evs, rate, (ev) => setSides((prev) => prev.map((s) => (s.driver === ev.side ? reduce(s, ev) : s))));
    setStatus(`Replaying ${names.join(" and ")} at ${rate}×`);
  }

  // ---- Claude Code race: replay ----
  async function startRace(name?: string, atSpeed?: number) {
    const n = name ?? pickedRace;
    const rate = atSpeed ?? speed;
    if (!n) return;
    const race = (await (await fetch(`${API}/api/race?name=${encodeURIComponent(n)}`)).json()) as SavedRace;
    stopAll();
    setSides([]);
    const order: RaceSide[] = ["baseline", "jevsight"];
    setRaceSides(order.map(emptyRaceSide));
    const evs: (RaceEvent & { side: RaceSide })[] = [];
    for (const side of order) for (const e of race.sides[side] ?? []) evs.push({ ...e, side });
    evs.sort((x, y) => x.t - y.t);
    playback(evs, rate, (ev) => setRaceSides((prev) => prev.map((s) => (s.side === ev.side ? reduceRace(s, ev) : s))));
    setStatus(`Replaying ${n} at ${rate}×`);
  }

  // ---- Claude Code race: live (race.py runs both sides; the page rebuilds the timeline from the files every 2 s) ----
  async function startLiveRace() {
    stopAll();
    setSides([]);
    setBusy(true);
    setStatus("Starting both Claude Code sessions…");
    const r = (await (await fetch(`${API}/api/race/start`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ app: raceApp }) })).json()) as {
      name?: string;
      error?: string;
    };
    if (!r.name) {
      setStatus(r.error ?? "Could not start the race");
      setBusy(false);
      return;
    }
    const name = r.name;
    setPickedRace(name);
    setStatus(`Racing (${name})`);
    const order: RaceSide[] = ["baseline", "jevsight"];
    const t0 = performance.now();
    const refresh = async () => {
      const race = (await (await fetch(`${API}/api/race?name=${encodeURIComponent(name)}`)).json()) as SavedRace;
      const elapsed = (performance.now() - t0) / 1000;
      setRaceSides(
        order.map((side) => {
          let s = emptyRaceSide(side);
          for (const e of race.sides[side] ?? []) s = reduceRace(s, e);
          return s.done ? s : { ...s, clock: elapsed };
        }),
      );
      if (!race.running) {
        stopAll();
        setBusy(false);
        setStatus("Race finished");
        loadRuns();
      }
    };
    setRaceSides(order.map(emptyRaceSide));
    await refresh();
    poll.current = window.setInterval(refresh, 2000);
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
    if (autoplayed.current || (!runs.length && !races.length)) return;
    const q = new URLSearchParams(window.location.search);
    const rate = parseFloat(q.get("speed") ?? "") || speed;
    const replay = (q.get("replay") ?? "").split(",").filter(Boolean);
    const race = q.get("race");
    if (!replay.length && !race) return;
    autoplayed.current = true;
    setSpeed(rate);
    if (race) {
      setTab("race");
      setPickedRace(race);
      startRace(race, rate);
    } else {
      setPicked(replay);
      startReplay(replay, rate);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runs, races]);

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
        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={tab === "loop"} className={tab === "loop" ? "active" : ""} onClick={() => setTab("loop")}>
            Agent loop
          </button>
          <button role="tab" aria-selected={tab === "race"} className={tab === "race" ? "active" : ""} onClick={() => setTab("race")}>
            Claude Code race
          </button>
        </div>
        <span className="keys">{config ? `${config.model} · Anthropic key ${config.have_anthropic_key ? "on" : "missing"} · Jev key ${config.have_jev_key ? "on" : "missing"}` : "connecting to the API…"}</span>
      </div>

      <main>
        {tab === "loop" ? (
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
        ) : (
          <section className="hero">
            <div>
              <h1>Same Claude Code, same prompt. One side has the proxy.</h1>
              <p className="lede">
                The Jevsight proxy sits between Claude Code and its MCP server. While Claude thinks, Jev predicts the next call and the proxy runs it early. Green calls were already answered when Claude
                asked.
              </p>
              <div className="row">
                <label>Task</label>
                <select value={raceApp} onChange={(e) => setRaceApp(e.target.value)}>
                  {config &&
                    Object.entries(config.apps).map(([k, v]) => (
                      <option value={k} key={k}>
                        {k} ({v.server})
                      </option>
                    ))}
                </select>
                <button className="btn primary" onClick={startLiveRace} disabled={busy}>
                  Run a new race
                </button>
                <span className="hint-inline">Two Claude Code sessions start together; takes a few minutes.</span>
              </div>
              <div className="row">
                <select value={pickedRace} onChange={(e) => setPickedRace(e.target.value)} style={{ minWidth: 420, fontFamily: "var(--font-mono)", fontSize: 12 }}>
                  <option value="">Replay a recorded race…</option>
                  {races.map((r) => (
                    <option value={r.name} key={r.name}>
                      {r.name.slice(5)} {(r.app || "?").padEnd(10)}
                      {r.running ? " running now" : ` plain ${r.baseline.seconds}s / ${r.baseline.wait_s}s waited · proxy ${r.jevsight.seconds}s / ${r.jevsight.wait_s}s waited`}
                    </option>
                  ))}
                </select>
                <label>Speed</label>
                <select value={speed} onChange={(e) => setSpeed(parseFloat(e.target.value))}>
                  {SPEEDS.map((s) => (
                    <option value={s} key={s}>
                      {s}×
                    </option>
                  ))}
                </select>
                <button className="btn ghost" onClick={() => startRace()} disabled={!pickedRace || busy}>
                  Play
                </button>
              </div>
              <div className="status">{status}</div>
            </div>
            <div className="side-panel">
              <h2>How to read it</h2>
              <p>Each tool call shows how long Claude waited for it. On the proxy side, orange cards are Jev's predictions with the expected-value decision per candidate, and green calls were served from a result that was already running.</p>
              <p>Races are recorded by race/race.py with the same model, prompt and server on both sides, started at the same moment.</p>
            </div>
          </section>
        )}

        {tab === "loop" && <Compare sides={sides} />}
        {tab === "race" && raceSides.length === 2 && raceSides.every((s) => s.result) && (
          <div className="compare">
            <div className="tile">
              <b>{`${(100 * (raceSides[1].result!.t - raceSides[0].result!.t) / raceSides[0].result!.t).toFixed(0)}%`}</b>
              <span>wall · {raceSides[0].result!.t.toFixed(1)}s → {raceSides[1].result!.t.toFixed(1)}s</span>
            </div>
            <div className="tile">
              <b>{`${(100 * (raceSides[1].waited - raceSides[0].waited) / raceSides[0].waited).toFixed(0)}%`}</b>
              <span>time waiting on tools · {raceSides[0].waited.toFixed(1)}s → {raceSides[1].waited.toFixed(1)}s</span>
            </div>
            <div className="tile">
              <b>
                {raceSides[1].hits}/{raceSides[1].calls}
              </b>
              <span>calls answered before Claude asked</span>
            </div>
            <div className="tile">
              <b>${raceSides[1].result!.cost_usd.toFixed(2)}</b>
              <span>proxy side cost · plain ${raceSides[0].result!.cost_usd.toFixed(2)}</span>
            </div>
          </div>
        )}

        <div className={`columns${sides.length === 2 || raceSides.length === 2 ? " two" : ""}`}>
          {tab === "loop" && sides.map((s) => <RunColumn side={s} key={s.driver} />)}
          {tab === "race" && raceSides.map((s) => <RaceColumn side={s} key={s.side} />)}
        </div>
      </main>
    </>
  );
}

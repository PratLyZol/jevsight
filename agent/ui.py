#!/usr/bin/env python3
"""Jevsight agent API: runs the Claude / Claude+Jev loop and streams every turn to the TypeScript UI in web/.

  python3 agent/ui.py                # API on http://127.0.0.1:8765
  cd web && npm run dev              # UI on http://localhost:3000 (proxies /api/* here)

Standard library only. Live runs use the same harness as `agent/jevloop.py` (same run directories, same
loops.jsonl records); replay serves any saved run directory for the UI to play back on its timeline.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import subprocess
import threading
import time
from datetime import datetime
import types
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for d in ("agent", "race", os.path.join("plugins", "jevsight", "bin"), "tests"):
    sys.path.insert(0, os.path.join(ROOT, d))

import jevloop  # noqa: E402
import race  # noqa: E402

UI_URL = os.environ.get("JEVSIGHT_UI_URL", "http://localhost:3000")
RUNS_DIR = os.path.expanduser(os.environ.get("JEVSIGHT_RUNS_DIR", "~/jevsight-races"))
MCP_APPS = {k: v for k, v in race.APPS.items() if v["kind"] == "mcp"}
DRIVERS = ("llm", "jev", "cascade")


class Job:
    """One button press: one or more drivers running the same task, each streaming events."""

    def __init__(self, drivers):
        self.id = uuid.uuid4().hex[:8]
        self.events = []            # [{"side": driver, ...record}]
        self.cond = threading.Condition()
        self.pending = set(drivers)

    def push(self, side, rec):
        with self.cond:
            self.events.append(dict(rec, side=side))
            if rec.get("kind") in ("done", "error"):
                self.pending.discard(side)
            self.cond.notify_all()

    def finished(self):
        return not self.pending


JOBS: dict[str, Job] = {}
WARMED = set()
WARM_LOCK = threading.Lock()


def run_args(body):
    app = body.get("app") or "fetch"
    if app not in MCP_APPS:
        raise ValueError("unknown app %r" % app)
    task = (body.get("task") or "").strip() or None
    return types.SimpleNamespace(
        app=app, prompt=task, model=body.get("model") or os.environ.get("LOOP_MODEL", "claude-opus-5-5"),
        small_model=body.get("small_model") or os.environ.get("LOOP_SMALL_MODEL", "claude-haiku-4-5-20251001"),
        small_max_tokens=1024, cache=bool(body.get("cache", True)), threshold=float(body.get("threshold", 0.4)),
        max_chain=12, max_turns=int(body.get("max_turns", 40)), runs_dir=RUNS_DIR, server_cmd=None)


def start_job(body):
    drivers = [d for d in (body.get("drivers") or ["jev"]) if d in DRIVERS]
    if not drivers:
        raise ValueError("no driver selected")
    a = run_args(body)
    job = Job(drivers)
    JOBS[job.id] = job
    stamp = time.strftime("%Y%m%d-%H%M%S")

    def side(driver):
        try:
            with WARM_LOCK:
                if a.app not in WARMED:
                    job.push(driver, {"kind": "warming", "t": 0, "app": a.app})
                    race.warm(MCP_APPS[a.app], a)
                    WARMED.add(a.app)
            run_dir = os.path.join(RUNS_DIR, "loop-%s-%s" % (stamp, driver))
            res = jevloop.Run(a, driver, run_dir, on_event=lambda rec: job.push(driver, rec)).run()
            with open(os.path.join(RUNS_DIR, "loops.jsonl"), "a") as f:
                f.write(json.dumps(res) + "\n")
        except Exception as e:  # noqa: BLE001 - surface anything to the page
            job.push(driver, {"kind": "error", "t": 0, "error": str(e)[:500]})

    for d in drivers:
        threading.Thread(target=side, args=(d,), daemon=True, name="run-" + d).start()
    return job


def list_runs():
    out = []
    if not os.path.isdir(RUNS_DIR):
        return out
    for name in sorted(os.listdir(RUNS_DIR), reverse=True):
        p = os.path.join(RUNS_DIR, name, "result.json")
        if name.startswith("loop-") and os.path.isfile(p):
            try:
                r = json.load(open(p))
            except (OSError, ValueError):
                continue
            out.append({"name": name, "driver": r.get("driver"), "app": r.get("app"), "wall_s": r.get("wall_s"),
                        "turns": r.get("claude_turns"), "tools": r.get("tool_calls"), "input_tokens": r.get("input_tokens"),
                        "cache": r.get("cache"), "threshold": r.get("threshold"), "pages_named": len(r.get("pages_named") or []),
                        "stamp": name[5:20]})
    return out


def load_run(name):
    if "/" in name or ".." in name or not name.startswith("loop-"):
        raise ValueError("bad run name")
    d = os.path.join(RUNS_DIR, name)
    events = [json.loads(l) for l in open(os.path.join(d, "trace.jsonl")) if l.strip()]
    result = json.load(open(os.path.join(d, "result.json")))
    try:
        answer = open(os.path.join(d, "answer.md")).read()
    except OSError:
        answer = ""
    if not any(e.get("kind") == "start" for e in events):   # runs recorded before the start event existed
        events.insert(0, {"kind": "start", "t": 0, "driver": result.get("driver"), "model": result.get("model"),
                          "app": result.get("app"), "task": race.APPS.get(result.get("app"), {}).get("prompt", ""),
                          "threshold": result.get("threshold"), "cache": result.get("cache", False)})
    if not any(e.get("kind") == "done" for e in events):
        events.append({"kind": "done", "t": result.get("wall_s", 0), "result": result, "answer": answer})
    return {"name": name, "events": events, "result": result, "answer": answer}


# ---------- plain Claude Code on the same task (race/race.py --only baseline) ----------
CC_PROCS: dict[str, subprocess.Popen] = {}   # race dir name -> race.py process started from the UI


def _iso(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() if ts else None


def cc_events(run_dir):
    """A Claude Code session's stream file as timeline events with seconds since it started."""
    path = os.path.join(run_dir, "baseline.stream.jsonl")
    if not os.path.isfile(path):
        return []
    lines = [l for l in open(path) if l.strip()]
    times = {}
    try:
        for l in open(os.path.join(run_dir, "baseline.times.jsonl")):
            if l.strip():
                r = json.loads(l)
                times[r["line"]] = r["t"]
    except OSError:
        pass
    start_abs, events, pending = None, [], {}
    for i, l in enumerate(lines):
        try:
            e = json.loads(l)
        except ValueError:
            continue
        t = times.get(i)
        ts = _iso(e.get("timestamp")) if isinstance(e.get("timestamp"), str) else None
        if start_abs is None and ts is not None and t is not None:
            start_abs = ts - t
        if t is None and ts is not None and start_abs is not None:
            t = ts - start_abs
        if t is None:
            t = events[-1]["t"] if events else 0.0
        t = round(t, 3)
        typ = e.get("type")
        msg = e.get("message") if isinstance(e.get("message"), dict) else {}
        content = msg.get("content") if isinstance(msg.get("content"), list) else []
        if typ == "assistant":
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and (b.get("text") or "").strip() and e.get("parent_tool_use_id") is None:
                    events.append({"kind": "narration", "t": t, "text": b["text"][:600]})
                elif b.get("type") == "tool_use":
                    name = b.get("name") or ""
                    if name.startswith("mcp__"):
                        ev = {"kind": "call", "t": t, "id": b.get("id"), "tool": name.split("__", 2)[-1], "args": b.get("input") or {}}
                        events.append(ev)
                        pending[b.get("id")] = ev
        elif typ == "user":
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in pending:
                    call = pending.pop(b["tool_use_id"])
                    c = b.get("content")
                    text = c if isinstance(c, str) else " ".join(x.get("text", "") for x in c if isinstance(x, dict)) if isinstance(c, list) else ""
                    events.append({"kind": "result", "t": t, "id": call["id"], "tool": call["tool"], "wait": round(t - call["t"], 3),
                                   "chars": len(text), "error": bool(b.get("is_error"))})
        elif typ == "result":
            u = e.get("usage") or {}
            try:
                answer = open(os.path.join(run_dir, "baseline.answer.md")).read()
            except OSError:
                answer = ""
            events.append({"kind": "done", "t": round(e.get("duration_ms", 0) / 1000, 3), "num_turns": e.get("num_turns"),
                           "cost_usd": e.get("total_cost_usd"), "output_tokens": u.get("output_tokens"), "answer": answer,
                           "input_tokens": (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0)})
    return events


def cc_running(name):
    p = CC_PROCS.get(name)
    return p is not None and p.poll() is None


def load_cc(name):
    if "/" in name or ".." in name or not name.startswith("race-"):
        raise ValueError("bad run name")
    d = os.path.join(RUNS_DIR, name)
    try:
        task = open(os.path.join(d, "prompt.txt")).read()
    except OSError:
        task = ""
    events = [{"kind": "start", "t": 0.0, "task": task[:2000]}] + cc_events(d)
    return {"name": name, "task": task, "running": cc_running(name), "events": events}


def list_cc():
    """Claude Code sessions recorded by race.py (their baseline side), newest first."""
    out = []
    if not os.path.isdir(RUNS_DIR):
        return out
    for n in sorted(os.listdir(RUNS_DIR), reverse=True):
        d = os.path.join(RUNS_DIR, n)
        if not n.startswith("race-") or not os.path.isfile(os.path.join(d, "baseline.stream.jsonl")):
            continue
        try:
            task = open(os.path.join(d, "prompt.txt")).read().strip()
        except OSError:
            task = ""
        app = next((k for k, v in MCP_APPS.items() if v["prompt"].strip() == task), "custom")
        done = None
        for l in reversed(open(os.path.join(d, "baseline.stream.jsonl")).readlines()[-3:]):
            try:
                e = json.loads(l)
            except ValueError:
                continue
            if e.get("type") == "result":
                done = e
                break
        calls = sum(1 for l in open(os.path.join(d, "baseline.stream.jsonl")) if '"name": "mcp__' in l or '"name":"mcp__' in l)
        out.append({"name": n, "app": app, "running": cc_running(n), "seconds": round(done["duration_ms"] / 1000, 1) if done else None,
                    "turns": done.get("num_turns") if done else None, "calls": calls, "cost_usd": done.get("total_cost_usd") if done else None,
                    "task": task[:120]})
    return out


def start_versus(body):
    """Plain Claude Code and the Claude + Jev loop on the same task, started together."""
    app = body.get("app") or "fetch"
    if app not in MCP_APPS:
        raise ValueError("unknown app %r" % app)
    task = (body.get("task") or "").strip()
    before = set(os.listdir(RUNS_DIR)) if os.path.isdir(RUNS_DIR) else set()
    cmd = [sys.executable, os.path.join(ROOT, "race", "race.py"), "--app", app, "--only", "baseline", "--no-ui", "--runs-dir", RUNS_DIR]
    if task and task != MCP_APPS[app]["prompt"].strip():
        cmd += ["--prompt", task]
    log = open(os.path.join(RUNS_DIR, "claude-code-ui.log"), "a")
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    name = None
    for _ in range(100):
        time.sleep(0.2)
        new = [n for n in os.listdir(RUNS_DIR) if n.startswith("race-") and n not in before and os.path.isdir(os.path.join(RUNS_DIR, n))]
        if new:
            name = sorted(new)[-1]
            break
    if name is None:
        proc.kill()
        raise ValueError("race.py did not start; see %s" % os.path.join(RUNS_DIR, "claude-code-ui.log"))
    CC_PROCS[name] = proc
    job = start_job({"task": task, "app": app, "drivers": ["jev"], "threshold": body.get("threshold", 0.4)})
    return {"cc": name, "job": job.id}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet
        pass

    def end_headers(self):   # the Next.js dev server proxies /api/*, but allow a direct origin too
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def send_json(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlsplit(self.path)
        q = parse_qs(u.query)
        try:
            if u.path == "/":
                self.send_response(302)
                self.send_header("Location", UI_URL)
                self.end_headers()
            elif u.path == "/api/config":
                self.send_json({"apps": {k: {"prompt": v["prompt"], "server": v["server"]} for k, v in MCP_APPS.items()},
                                "drivers": DRIVERS, "model": os.environ.get("LOOP_MODEL", "claude-opus-5-5"),
                                "small_model": os.environ.get("LOOP_SMALL_MODEL", "claude-haiku-4-5-20251001"),
                                "have_anthropic_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
                                "have_jev_key": bool(os.environ.get("AI_GATEWAY_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
                                                     or os.environ.get("JEVSIGHT_API_KEY")), "runs_dir": RUNS_DIR})
            elif u.path == "/api/runs":
                self.send_json(list_runs())
            elif u.path == "/api/run":
                self.send_json(load_run(q.get("name", [""])[0]))
            elif u.path == "/api/cc":
                self.send_json(load_cc(q.get("name", [""])[0]))
            elif u.path == "/api/ccruns":
                self.send_json(list_cc())
            elif u.path == "/api/events":
                self.stream(q.get("job", [""])[0])
            else:
                self.send_json({"error": "not found"}, 404)
        except (OSError, ValueError, KeyError) as e:
            self.send_json({"error": str(e)}, 400)

    def do_POST(self):
        u = urlsplit(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        try:
            if u.path == "/api/run":
                if not os.environ.get("ANTHROPIC_API_KEY"):
                    raise ValueError("ANTHROPIC_API_KEY is not set (add it to .env)")
                job = start_job(body)
                self.send_json({"job": job.id})
            elif u.path == "/api/versus":
                if not os.environ.get("ANTHROPIC_API_KEY"):
                    raise ValueError("ANTHROPIC_API_KEY is not set (add it to .env)")
                self.send_json(start_versus(body))
            else:
                self.send_json({"error": "not found"}, 404)
        except ValueError as e:
            self.send_json({"error": str(e)}, 400)

    def stream(self, job_id):
        job = JOBS.get(job_id)
        if job is None:
            return self.send_json({"error": "no such job"}, 404)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        i = 0
        while True:
            with job.cond:
                if i >= len(job.events):
                    job.cond.wait(timeout=1.0)
                batch = job.events[i:]
                i = len(job.events)
                done = job.finished() and i >= len(job.events)
            try:
                for ev in batch:
                    self.wfile.write(("data: %s\n\n" % json.dumps(ev)).encode())
                if not batch:
                    self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
            if done:
                self.wfile.write(b"event: end\ndata: {}\n\n")
                self.wfile.flush()
                return


def main():
    race.load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    srv.daemon_threads = True
    print("Jevsight agent API: http://%s:%d   UI: %s (cd web && npm run dev)   runs in %s" % (a.host, a.port, UI_URL, RUNS_DIR))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

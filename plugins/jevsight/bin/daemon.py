#!/usr/bin/env python3
"""Jevsight daemon: one per machine, shared by every Claude Code session.

Hooks send it events over a unix socket. After each tool result it predicts the
next shell command, runs the ones whose expected value is positive, and when
Claude asks for a command it already ran, tells the PreToolUse hook to swap in
a replay of the saved output.
"""
from __future__ import annotations

import asyncio
import fcntl
import json
import os
import shlex
import signal
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from common import data_dir, log_event, mode, opt, sock_path  # noqa: E402
from predictor import HeuristicPredictor, PredictionError, make_predictor, render_state  # noqa: E402
from safety import canonical, classify, core, normalize, split_command  # noqa: E402
from narration import is_narration, n_tool_steps, narration_step, session_tail, trace_steps  # noqa: E402

FULL_RESULT_CHARS = 1000   # the newest few command outputs are shown to Jev at this length, older ones at 240

WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
READ_TOOLS = {"Read", "Grep", "Glob", "LS", "WebFetch", "WebSearch"}
JOB_TIMEOUT = 300.0
IDLE_EXIT = 6 * 3600


def ewma(old, new, a=0.3):
    return new if old is None else (1 - a) * old + a * new


class Job:
    def __init__(self, cmd, cwd, version, session, p, ev, pred_id):
        self.id = uuid.uuid4().hex[:12]
        self.cmd, self.cwd, self.version, self.session = cmd, cwd, version, session
        self.p, self.ev, self.pred_id = p, ev, pred_id
        self.dir = os.path.join(data_dir(), "jobs", self.id)
        os.makedirs(self.dir, exist_ok=True)
        self.start = None
        self.end = None
        self.rc = None
        self.proc = None
        self.status = "queued"  # queued, running, done, killed
        self.used_at = None

    @property
    def key(self):
        return (self.cwd, self.version, self.cmd)


class Session:
    def __init__(self, sid, cwd):
        self.id, self.cwd = sid, cwd
        self.prompt = ""
        self.steps = []        # short trace lines (tool calls and Claude's narration)
        self.steps_full = []   # same lines, command output at full length (the newest few are shown that way)
        self.tail = None       # TranscriptTail on this session's transcript, once a hook tells us the path
        self.pred_before = None
        self.narrated = False
        self.cmd_history = []
        self.version = 0
        self.last_result_ts = None
        self.think = None  # EWMA seconds from tool result to next tool call
        self.last_action = "none"
        self.edited_since_check = False
        self.last_check = "none"
        self.pred = None  # latest prediction awaiting its outcome
        self.pred_seq = 0


class Daemon:
    def __init__(self):
        self.sessions = {}
        self.jobs = {}
        self.by_key = {}
        self.tool_time = {}
        self.max_workers = int(opt("max_workers", "4") or 4)
        self.alpha = float(opt("alpha", "0.25") or 0.25)
        self.max_launch = int(opt("max_launch", "2") or 2)
        self.running = 0
        self.predictor = make_predictor()
        self.fallback = HeuristicPredictor()
        self.last_activity = time.time()
        self.hist_path = os.path.join(data_dir(), "history.json")
        try:
            with open(self.hist_path) as f:
                self.project_hist = json.load(f)
        except (OSError, ValueError):
            self.project_hist = {}
        log_event("daemon_start", predictor=self.predictor.name, mode=mode(), pid=os.getpid(),
                  alpha=self.alpha, max_workers=self.max_workers)

    # ---------- sessions and history ----------
    def session(self, payload):
        sid = payload.get("session_id") or "unknown"
        cwd = payload.get("cwd") or os.getcwd()
        s = self.sessions.get(sid)
        if s is None:
            s = self.sessions[sid] = Session(sid, cwd)
        s.cwd = cwd or s.cwd
        if s.tail is None:
            s.tail = session_tail(payload.get("transcript_path"))
        return s

    # ---------- Claude's narration ----------
    def absorb_narration(self, s, inflight=False):
        """Add what Claude has said since the last poll. `inflight`: a hook for a call is being handled,
        so the words belong to that call and go at the end. Otherwise words that came with a call whose
        result is already the last step (transcript source) go back in front of that step.
        Returns True if any of the words look ahead to a call not made yet."""
        ahead = False
        for it in (s.tail.poll() if s.tail else []):
            line = narration_step(it["text"])
            j = None if inflight else self.place_before(s, it.get("then_tool"))
            if j is None:
                self.add_step(s, line)
                ahead = ahead or not it.get("then_tool")
            else:
                s.steps.insert(j, line)
                s.steps_full.insert(j, line)
            log_event("narration", session=s.id, cwd=s.cwd, text=it["text"][:200], n_calls=n_tool_steps(s.steps),
                      with_call=it.get("then_tool"), placed="before_last_step" if j is not None else "end")
        return ahead

    def place_before(self, s, then_tool):
        if not then_tool or not s.last_result_ts or time.time() - s.last_result_ts > 5.0:
            return None
        for j in range(len(s.steps) - 1, -1, -1):
            st = s.steps[j]
            if is_narration(st):
                continue
            return j if st.startswith("Bash `" if then_tool == "Bash" else then_tool + " ") else None
        return None

    async def watch_narration(self, s, seq):
        """While Claude thinks after a result, watch the transcript: as soon as Claude narrates its
        next move, predict again with those words in the state."""
        deadline = time.time() + 45.0
        while time.time() < deadline and seq == s.pred_seq:
            await asyncio.sleep(0.15)
            if seq != s.pred_seq:
                return
            if self.absorb_narration(s):
                s.narrated = True
                self.schedule_prediction(s)
                return

    def add_step(self, s, short, full=None):
        s.steps.append(short)
        s.steps_full.append(full or short)
        s.steps, s.steps_full = s.steps[-400:], s.steps_full[-400:]

    def remember_command(self, s, cmd):
        s.cmd_history.append(cmd)
        h = self.project_hist.setdefault(s.cwd, {})
        h[cmd] = h.get(cmd, 0) + 1
        try:
            with open(self.hist_path, "w") as f:
                json.dump(self.project_hist, f)
        except OSError:
            pass

    def candidates(self, s):
        seen, out = set(), []

        def add(c):
            if not classify(c, s.cwd):
                return
            c = canonical(c)
            if c and c not in seen and classify(c, s.cwd):
                seen.add(c)
                out.append(c)

        for c in reversed(s.cmd_history):
            add(c)
        for c, _n in sorted(self.project_hist.get(s.cwd, {}).items(), key=lambda kv: -kv[1]):
            add(c)
        try:
            with open(os.path.join(s.cwd, "package.json")) as f:
                scripts = (json.load(f).get("scripts") or {})
            if "test" in scripts:
                add("npm test")
            for name in ("typecheck", "lint", "check", "test"):
                if name in scripts:
                    add("npm run %s" % name)
        except (OSError, ValueError):
            pass
        for c in ("git status", "git diff", "ls"):
            add(c)
        return out[:60]

    def facts(self, s):
        streak = 0
        for st in reversed(s.steps):
            if is_narration(st):
                continue
            if st.split(" ", 1)[0] in WRITE_TOOLS:
                streak += 1
            else:
                break
        return {
            "last_action": s.last_action,
            "file_edits_in_a_row_just_now": streak,
            "total_tool_calls_so_far": n_tool_steps(s.steps),
            "shell_commands_run_so_far": len(s.cmd_history),
            "files_edited_since_last_check": "yes" if s.edited_since_check else "no",
            "last_check_result": s.last_check,
            "distinct_commands_run_so_far": ", ".join(dict.fromkeys(canonical(c) for c in reversed(s.cmd_history[-12:]))) or "none",
        }

    # ---------- versions and jobs ----------
    def bump(self, s, why):
        s.version += 1
        for job in list(self.jobs.values()):
            if job.cwd == s.cwd and job.version < s.version and job.status in ("queued", "running"):
                self.kill(job, "stale:" + why)

    def kill(self, job, reason):
        if job.proc and job.status == "running":
            try:
                os.killpg(job.proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        if job.status in ("queued", "running"):
            job.status = "killed"
            wasted = (time.time() - job.start) if job.start else 0.0
            log_event("wasted", session=job.session, cwd=job.cwd, cmd=job.cmd, job=job.id,
                      wasted_s=round(wasted, 3), reason=reason)

    async def run_job(self, job):
        self.running += 1
        job.status = "running"
        job.start = time.time()
        log_event("launch", session=job.session, cwd=job.cwd, cmd=job.cmd, job=job.id, p=round(job.p, 4),
                  ev=round(job.ev, 3), version=job.version, pred=job.pred_id)
        out = open(os.path.join(job.dir, "stdout"), "wb")
        err = open(os.path.join(job.dir, "stderr"), "wb")
        try:
            env = dict(os.environ, JEVSIGHT_SPECULATIVE="1")
            job.proc = await asyncio.create_subprocess_shell(
                job.cmd, cwd=job.cwd, stdout=out, stderr=err, stdin=asyncio.subprocess.DEVNULL,
                env=env, start_new_session=True)
            try:
                rc = await asyncio.wait_for(job.proc.wait(), timeout=JOB_TIMEOUT)
            except asyncio.TimeoutError:
                self.kill(job, "timeout")
                rc = -9
        except Exception as e:  # noqa: BLE001
            err.write(("jevsight: failed to start: %s\n" % e).encode())
            rc = 127
        finally:
            out.close()
            err.close()
            self.running -= 1
        job.end = time.time()
        job.rc = rc
        dur = job.end - job.start
        if job.status == "running":
            job.status = "done"
            self.tool_time[job.cmd] = ewma(self.tool_time.get(job.cmd), dur)
        with open(os.path.join(job.dir, "status.json.tmp"), "w") as f:
            json.dump({"rc": rc, "status": job.status, "start": job.start, "end": job.end, "cmd": job.cmd}, f)
        os.replace(os.path.join(job.dir, "status.json.tmp"), os.path.join(job.dir, "status.json"))
        if job.used_at is not None:
            saved = max(0.0, min(dur, job.used_at - job.start))
            log_event("saved", session=job.session, cwd=job.cwd, cmd=job.cmd, job=job.id,
                      saved_s=round(saved, 3), dur_s=round(dur, 3))
        log_event("job_done", session=job.session, cwd=job.cwd, cmd=job.cmd, job=job.id, rc=rc,
                  dur_s=round(dur, 3), status=job.status)

    # ---------- prediction ----------
    async def predict_and_launch(self, s, seq):
        # results from parallel tool calls land together: wait a moment. Narration is a single event
        # that arrives 0.3-0.5s before the call it announces: no time to spare.
        await asyncio.sleep(0.0 if s.narrated else float(opt("debounce", "0.15") or 0.15))
        if seq != s.pred_seq:
            return  # another tool result landed (parallel calls); predict once for the latest state
        cands = self.candidates(s)
        if not cands:
            return
        narrated, s.narrated = s.narrated, False
        state = render_state(s.prompt, trace_steps(s.steps, s.steps_full), self.facts(s))
        loop = asyncio.get_running_loop()
        t0 = time.time()
        predictor = self.predictor
        try:
            pred = await loop.run_in_executor(None, predictor.predict, state, cands)
        except PredictionError as e:
            log_event("predict_error", session=s.id, cwd=s.cwd, error=str(e)[:300], predictor=predictor.name)
            if opt("fallback", "none") != "heuristic":
                return
            predictor = self.fallback
            pred = predictor.predict(state, cands)
        latency = time.time() - t0
        if seq != s.pred_seq:
            return  # a newer tool result arrived while we were predicting
        probs = pred["commands"]
        ranked = sorted(probs.items(), key=lambda kv: -kv[1])
        pred_id = uuid.uuid4().hex[:10]
        think = s.think if s.think is not None else 6.0
        if s.last_result_ts:  # part of the thinking gap has already passed (Jev latency, narration wait)
            think = max(0.2, think - (time.time() - s.last_result_ts))
        decisions = []
        launched = 0
        for cmd, p in ranked:
            t = self.tool_time.get(cmd, 3.0)
            ev = p * min(t, think) - (1 - p) * self.alpha * t
            decision = "skip"
            if ev > 0 and launched < self.max_launch:
                key = (s.cwd, s.version, cmd)
                existing = self.by_key.get(key)
                if existing and existing.status in ("running", "done", "queued"):
                    decision = "have"
                elif mode() == "on" and self.running < self.max_workers:
                    job = Job(cmd, s.cwd, s.version, s.id, p, ev, pred_id)
                    self.jobs[job.id] = job
                    self.by_key[key] = job
                    asyncio.ensure_future(self.run_job(job))
                    decision = "launch"
                    launched += 1
                elif mode() == "shadow":
                    decision = "would_launch"
                    launched += 1
                else:
                    decision = "no_slot"
            decisions.append({"cmd": cmd, "p": round(p, 4), "ev": round(ev, 3), "decision": decision})
        if narrated and s.pred is not None:
            s.pred_before = s.pred
        s.pred = {"id": pred_id, "probs": probs, "p_run": pred.get("p_run", 0.0),
                  "launch": [d["cmd"] for d in decisions if d["decision"] in ("launch", "would_launch", "have")],
                  "narrated": narrated}
        log_event("predict", session=s.id, cwd=s.cwd, pred=pred_id, predictor=predictor.name, route=pred.get("route"),
                  latency_s=round(latency, 3), p_run=round(pred.get("p_run", 0.0), 4),
                  top=decisions[:5], n_candidates=len(cands), version=s.version, after_narration=narrated,
                  supersedes=(s.pred_before or {}).get("id") if narrated else None)

    def resolve_prediction(self, s, actual_cmd, actual_kind):
        pr, before = s.pred, s.pred_before
        s.pred = s.pred_before = None
        s.narrated = False
        if not pr:
            return
        actual_cmd = canonical(actual_cmd) if actual_cmd else actual_cmd
        p_actual = pr["probs"].get(actual_cmd, 0.0) if actual_cmd else 0.0
        extra = {}
        if before:
            extra = {"p_actual_before_narration": round(before["probs"].get(actual_cmd, 0.0) if actual_cmd else 0.0, 4),
                     "would_hit_before_narration": bool(actual_cmd and actual_cmd in before["launch"])}
        log_event("outcome", session=s.id, cwd=s.cwd, pred=pr["id"], actual_kind=actual_kind,
                  actual_cmd=actual_cmd, p_actual=round(p_actual, 4), p_run=round(pr["p_run"], 4),
                  probs={k: round(v, 4) for k, v in sorted(pr["probs"].items(), key=lambda kv: -kv[1])[:10]},
                  would_hit=bool(actual_cmd and actual_cmd in pr["launch"]), after_narration=pr.get("narrated", False),
                  **extra)

    def schedule_prediction(self, s):
        if mode() == "off":
            return
        s.pred_seq += 1
        asyncio.ensure_future(self.predict_and_launch(s, s.pred_seq))
        asyncio.ensure_future(self.watch_narration(s, s.pred_seq))

    # ---------- hook events ----------
    async def on_event(self, event, payload):
        self.last_activity = time.time()
        s = self.session(payload)
        if event == "UserPromptSubmit":
            self.resolve_prediction(s, None, "finish")
            s.prompt = payload.get("prompt") or s.prompt
            s.last_result_ts = time.time()
            self.schedule_prediction(s)
            return {}
        if event == "PreToolUse":
            return self.on_pre(s, payload)
        if event in ("PostToolUse", "PostToolUseFailure"):
            self.on_post(s, payload, failed=(event == "PostToolUseFailure"))
            return {}
        return {}

    def on_pre(self, s, payload):
        tool = payload.get("tool_name")
        now = time.time()
        if s.last_result_ts:
            s.think = ewma(s.think, now - s.last_result_ts)
        self.absorb_narration(s, inflight=True)   # what Claude said just before this call belongs before it
        if tool != "Bash":
            return {}
        raw = (payload.get("tool_input") or {}).get("command") or ""
        cmd = normalize(raw)
        self.resolve_prediction(s, cmd, "run_command")
        if (payload.get("tool_input") or {}).get("run_in_background"):
            return {}
        kind = classify(cmd, s.cwd)
        if kind is None:
            self.bump(s, "bash:" + core(cmd)[:40])
            return {}
        parts = split_command(cmd)
        key_cmd = parts[1] if parts else cmd
        job = self.by_key.get((s.cwd, s.version, key_cmd))
        if mode() != "on" or job is None or job.status not in ("running", "done"):
            log_event("miss", session=s.id, cwd=s.cwd, cmd=key_cmd, raw=cmd, had_job=job is not None)
            if kind == "allowed":
                # Tests and builds can write caches and build output. Never let a
                # speculative one run alongside a different one Claude just started.
                for other in list(self.jobs.values()):
                    if other.cwd == s.cwd and other.status == "running" and classify(other.cmd, s.cwd) == "allowed":
                        self.kill(other, "superseded")
            return {}
        job.used_at = now
        log_event("hit", session=s.id, cwd=s.cwd, cmd=key_cmd, raw=cmd, job=job.id, job_status=job.status,
                  p=round(job.p, 4), head_start_s=round(now - job.start, 3))
        if job.status == "done" and job.end is not None:
            dur = job.end - job.start
            log_event("saved", session=s.id, cwd=s.cwd, cmd=cmd, job=job.id,
                      saved_s=round(max(0.0, min(dur, now - job.start)), 3), dur_s=round(dur, 3))
        replay = "%s %s %s" % (shlex.quote(sys.executable), shlex.quote(os.path.join(HERE, "replay.py")),
                               shlex.quote(job.dir))
        if parts:
            # keep `cd X &&`, harmless env vars and `2>&1 | tail -N` exactly as Claude wrote them
            replay = parts[0] + replay + parts[2]
        return {"hook_output": {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": "Jevsight: result of `%s` was computed ahead of time" % cmd[:80],
            "updatedInput": {"command": replay},
        }}}

    def on_post(self, s, payload, failed=False):
        tool = payload.get("tool_name") or "?"
        ti = payload.get("tool_input") or {}
        resp = payload.get("tool_response")
        text = ""
        if isinstance(resp, dict):
            text = resp.get("text") or resp.get("stdout") or resp.get("output") or ""
            if resp.get("stderr"):
                text += "\n" + str(resp.get("stderr"))
        elif isinstance(resp, str):
            text = resp
        tail = " ".join(str(text)[-240:].split())
        full_tail = " ".join(str(text)[-FULL_RESULT_CHARS:].split())
        self.absorb_narration(s, inflight=True)
        if tool in WRITE_TOOLS:
            path = ti.get("file_path") or ti.get("notebook_path") or ""
            self.add_step(s, "%s %s" % (tool, os.path.relpath(path, s.cwd) if path.startswith("/") else path))
            s.last_action = "edit_file"
            s.edited_since_check = True
            self.resolve_prediction(s, None, "edit_file")
            self.bump(s, tool)
        elif tool == "Bash":
            cmd = normalize(ti.get("command") or "")
            if "replay.py" in cmd and "jevsight" in cmd.lower():
                cmd = self.original_for_replay(cmd) or cmd
            self.remember_command(s, cmd)
            self.add_step(s, "Bash `%s` -> %s%s" % (cmd[:120], "failed" if failed else "ok", (": " + tail) if tail else ""),
                          "Bash `%s` -> %s%s" % (cmd[:200], "failed" if failed else "ok", (": " + full_tail) if full_tail else ""))
            s.last_action = "run_command"
            kind = classify(cmd, s.cwd)
            if kind is None:
                self.bump(s, "bash-post")
            else:
                s.edited_since_check = False
                s.last_check = "failing" if failed else "passing"
        else:
            desc = ti.get("pattern") or ti.get("file_path") or ti.get("path") or ti.get("url") or ""
            self.add_step(s, "%s %s" % (tool, str(desc)[:120]))
            s.last_action = "read_file" if tool in READ_TOOLS else "other"
            self.resolve_prediction(s, None, "read_file" if tool in READ_TOOLS else "other")
        s.last_result_ts = time.time()
        self.schedule_prediction(s)

    def original_for_replay(self, cmd):
        for job in self.jobs.values():
            if job.dir in cmd:
                return job.cmd
        return None

    # ---------- server ----------
    async def handle(self, reader, writer):
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=5)
            msg = json.loads(line.decode() or "{}")
            if msg.get("event") == "ping":
                reply = {"ok": True, "pid": os.getpid()}
            else:
                reply = await self.on_event(msg.get("event"), msg.get("payload") or {})
        except Exception as e:  # noqa: BLE001
            log_event("daemon_error", error=repr(e)[:300])
            reply = {}
        try:
            writer.write((json.dumps(reply) + "\n").encode())
            await writer.drain()
        finally:
            writer.close()

    async def idle_watch(self):
        while True:
            await asyncio.sleep(60)
            if time.time() - self.last_activity > IDLE_EXIT and self.running == 0:
                log_event("daemon_exit", reason="idle")
                os._exit(0)


async def main():
    lock = open(os.path.join(data_dir(), "daemon.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return  # another daemon owns the socket
    path = sock_path()
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    d = Daemon()
    server = await asyncio.start_unix_server(d.handle, path=path)
    os.chmod(path, 0o600)
    asyncio.ensure_future(d.idle_watch())
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())

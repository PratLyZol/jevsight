#!/usr/bin/env python3
"""Rate-limit-proof benchmark: replay a recorded run through Jev offline.

Speculation never changes what Claude sees, so we can take a recorded baseline
trajectory (every tool call with real timestamps), ask Jev at each step what it
would have predicted (retrying patiently, no live deadline), and simulate what
Jevsight would have saved using the real call times and Claude's real thinking
times. Answers are cached in <race>/replay_cache.json, so reruns are free and an
interrupted run resumes where it stopped.

Two modes, picked from the trajectory (or --mode):
  bash  shell-command races (apps small/next/fix): candidates come from safety.py
  mcp   MCP races (app neon): candidates are rebuilt with the proxy's own code
        (mcp_proxy.build_candidates) from the tool schemas the proxy saved in
        <race>/jevsight-data/tools.json, and the same state text and questions.

Usage:
  python3 eval/replay_bench.py ~/jevsight-races/race-XXXX            # baseline side
  python3 eval/replay_bench.py ~/jevsight-races/race-XXXX --side jevsight
  python3 eval/replay_bench.py RACE --predictor heuristic            # no API calls
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "plugins", "jevsight", "bin"))
sys.path.insert(0, HERE)

from bench import brier, ece, load_jsonl  # noqa: E402

FIX_PROMPT = ("`npm run check` is failing on this expense tracker. Fix the code until it passes. "
              "Do not edit files under test/ or the config files.")
WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
READ_TOOLS = {"Read", "Grep", "Glob", "LS", "WebFetch", "WebSearch"}


def load_dotenv():
    path = os.path.join(ROOT, ".env")
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if v.strip():
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def trajectory(race, side):
    stream = load_jsonl(os.path.join(race, "%s.stream.jsonl" % side))
    times = {r["line"]: r["t"] for r in load_jsonl(os.path.join(race, "%s.times.jsonl" % side))}
    if not times:
        sys.exit("No %s.times.jsonl in %s. Only races run with the updated race.py have timestamps." % (side, race))
    calls, by_id, wall = [], {}, None
    for i, ev in enumerate(stream):
        t = times.get(i)
        if ev.get("type") == "assistant" and ev.get("parent_tool_use_id") is None:
            for c in (ev.get("message") or {}).get("content") or []:
                if c.get("type") == "tool_use":
                    rec = {"id": c["id"], "tool": c["name"], "input": c.get("input") or {}, "t_call": t,
                           "t_result": None, "error": False, "text": "", "narration": []}
                    calls.append(rec)
                    by_id[c["id"]] = rec
                elif c.get("type") == "text" and calls and (c.get("text") or "").strip():
                    # Claude's words after the previous result and before its next call
                    calls[-1]["narration"].append((t, c["text"]))
        elif ev.get("type") == "user":
            for c in (ev.get("message") or {}).get("content") or []:
                if c.get("type") == "tool_result" and c.get("tool_use_id") in by_id:
                    rec = by_id[c["tool_use_id"]]
                    rec["t_result"] = t
                    rec["error"] = bool(c.get("is_error"))
                    body = c.get("content")
                    if isinstance(body, list):
                        body = " ".join(x.get("text", "") for x in body if isinstance(x, dict))
                    rec["text"] = str(body or "")
        elif ev.get("type") == "result":
            wall = (ev.get("duration_ms") or 0) / 1000 or t
    return [c for c in calls if c["t_result"] is not None], wall


def ask(pred, cache, cache_path, key, fn, k):
    """Cached, patient prediction: retries with backoff, never gives up before 8 attempts."""
    from predictor import PredictionError
    if key in cache:
        return cache[key]
    probs = None
    for attempt in range(8):
        try:
            probs = fn()
            break
        except PredictionError as e:
            wait = min(30, 2 ** attempt)
            print("  step %d: %s; retrying in %ds" % (k, str(e)[:80], wait))
            time.sleep(wait)
    if probs is None:
        print("  step %d: giving up on this step" % k)
        probs = {"p_run": 0.0, "commands": {}}
    cache[key] = probs
    json.dump(cache, open(cache_path, "w"))
    return probs


# ---------------------------------------------------------------------------
# calibration: temperature scaling of the top choice, cross-fitted on two folds
def _logit(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def _sig(x):
    return 1 / (1 + math.exp(-x))


MIN_CALIB_STEPS = 10


def fit_temperature(pairs):
    """T minimising the log loss of sigmoid(logit(p)/T) on (p, y) pairs; grid search. Returns 1.0
    (no scaling) when there are too few steps to fit anything meaningful."""
    if len(pairs) < MIN_CALIB_STEPS:
        return 1.0
    best, best_t = None, 1.0
    for i in range(1, 81):
        t = i / 10.0
        nll = 0.0
        for p, y in pairs:
            q = min(max(_sig(_logit(p) / t), 1e-6), 1 - 1e-6)
            nll -= math.log(q) if y else math.log(1 - q)
        if best is None or nll < best - 1e-9:
            best, best_t = nll, t
    return best_t


def cross_fit_temperatures(predictions, top_of):
    """Two folds by step parity: each step gets a temperature fitted on the other fold."""
    pairs = {0: [], 1: []}
    for p in predictions:
        top = top_of(p)
        if top is not None:
            pairs[p["k"] % 2].append((p["probs"][top], 1 if p["hit_key"](top) else 0))
    t_for = {0: fit_temperature(pairs[1]), 1: fit_temperature(pairs[0])}
    return t_for


def scaled(probs, t):
    return {c: _sig(_logit(p) / t) for c, p in probs.items()}


# ---------------------------------------------------------------------------
def run_bash(a, race, calls, wall, pred, cache, cache_path):
    from predictor import render_state
    from safety import canonical, classify

    cwd = os.path.join(race, a.side)

    def candidates(history):
        seen, out = set(), []

        def add(c):
            if classify(c, cwd):
                c = canonical(c)
                if c not in seen:
                    seen.add(c)
                    out.append(c)
        for c in reversed(history):
            add(c)
        try:
            scripts = json.load(open(os.path.join(cwd, "package.json"))).get("scripts") or {}
            if "test" in scripts:
                add("npm test")
            for n in ("typecheck", "lint", "check", "test"):
                if n in scripts:
                    add("npm run %s" % n)
        except (OSError, ValueError):
            pass
        for c in ("git status", "git diff", "ls"):
            add(c)
        return out[:60]

    from narration import narration_step, n_tool_steps, trace_steps, is_narration
    steps, steps_full, history, predictions = [], [], [], []
    edited_since_check, last_action, last_check = False, "none", "none"
    print("Replaying %d tool calls from %s/%s through %s ..." % (len(calls), os.path.basename(race), a.side, pred.name))
    for k, c in enumerate(calls):
        tool, ti = c["tool"], c["input"]
        if tool in WRITE_TOOLS:
            path = ti.get("file_path") or ""
            steps.append("%s %s" % (tool, os.path.relpath(path, cwd) if path.startswith("/") else path))
            last_action, edited_since_check = "edit_file", True
        elif tool == "Bash":
            cmd = " ".join((ti.get("command") or "").split())
            history.append(cmd)
            tail = " ".join(c["text"][-240:].split())
            full_tail = " ".join(c["text"][-1000:].split())
            steps.append("Bash `%s` -> %s%s" % (cmd[:120], "failed" if c["error"] else "ok", (": " + tail) if tail else ""))
            steps_full.append("Bash `%s` -> %s%s" % (cmd[:200], "failed" if c["error"] else "ok", (": " + full_tail) if full_tail else ""))
            last_action = "run_command"
            if classify(cmd, cwd):
                edited_since_check, last_check = False, ("failing" if c["error"] else "passing")
        else:
            desc = ti.get("pattern") or ti.get("file_path") or ti.get("path") or ""
            steps.append("%s %s" % (tool, str(desc)[:120]))
            last_action = "read_file" if tool in READ_TOOLS else "other"
        if len(steps_full) < len(steps):
            steps_full.append(steps[-1])
        if k + 1 >= len(calls):
            break
        nxt = calls[k + 1]
        actual = canonical(nxt["input"].get("command", "")) if nxt["tool"] == "Bash" else None
        cands = candidates(history)

        def record(stage, t_ready):
            streak = 0
            for st in reversed(steps):
                if is_narration(st):
                    continue
                if st.split(" ", 1)[0] in WRITE_TOOLS:
                    streak += 1
                else:
                    break
            facts = {"last_action": last_action, "file_edits_in_a_row_just_now": streak,
                     "total_tool_calls_so_far": n_tool_steps(steps), "shell_commands_run_so_far": len(history),
                     "files_edited_since_last_check": "yes" if edited_since_check else "no",
                     "last_check_result": last_check,
                     "distinct_commands_run_so_far": ", ".join(dict.fromkeys(canonical(h) for h in reversed(history[-12:]))) or "none"}
            state = render_state(a.prompt or FIX_PROMPT, trace_steps(steps, steps_full), facts)
            key = hashlib.sha1((pred.name + state + "\x00".join(cands)).encode()).hexdigest()
            probs = ask(pred, cache, cache_path, key, lambda: pred.predict(state, cands), k)
            predictions.append({"k": k, "stage": stage, "t_ready": t_ready, "probs": probs.get("commands", {}),
                                "p_run": probs.get("p_run", 0.0), "actual": actual, "next_tool": nxt["tool"],
                                "hit_key": (lambda cmd, actual=actual: cmd == actual)})

        record("result", c["t_result"] + a.latency)   # right after the result, as the live daemon does
        if a.narration and c["narration"]:            # and again once Claude has narrated its next move
            for _tt, txt in c["narration"]:
                steps.append(narration_step(txt))
                steps_full.append(narration_step(txt))
            record("narration", max((tt if tt is not None else c["t_result"]) for tt, _ in c["narration"]) + a.latency)
        if (k + 1) % 10 == 0:
            print("  %d/%d steps" % (k + 1, len(calls) - 1))

    def simulate(policy):
        jobs, tool_time, think = {}, {}, None
        hits = launches = 0
        saved = wasted = 0.0
        last_result = None
        by_k = {}
        for p in predictions:   # one prediction per step, or two when Claude narrated (result, then narration)
            by_k.setdefault(p["k"], []).append(p)
        for k, c in enumerate(calls):
            now_call = c["t_call"]
            if last_result is not None:
                think = (now_call - last_result) if think is None else 0.7 * think + 0.3 * (now_call - last_result)
            dur = c["t_result"] - c["t_call"]
            if c["tool"] == "Bash":
                cmd = canonical(c["input"].get("command", ""))
                if cmd in jobs:
                    start = jobs.pop(cmd)
                    hits += 1
                    saved += max(0.0, min(dur, now_call - start))
                if classify(c["input"].get("command", ""), cwd):
                    tool_time[cmd] = dur if cmd not in tool_time else 0.7 * tool_time[cmd] + 0.3 * dur
                else:  # an unknown command may write files: guesses are thrown away
                    for j, st in jobs.items():
                        wasted += min(tool_time.get(j, 10.0), max(0.0, now_call - st))
                    jobs.clear()
            if c["tool"] in WRITE_TOOLS:
                for j, st in jobs.items():
                    wasted += min(tool_time.get(j, 10.0), max(0.0, c["t_result"] - st))
                jobs.clear()
            last_result = c["t_result"]
            for p, cmd in [(p, cmd) for p in by_k.get(k, []) for cmd in policy(p, tool_time, think)]:
                if cmd not in jobs:
                    jobs[cmd] = p["t_ready"]
                    launches += 1
        for j, st in jobs.items():
            wasted += tool_time.get(j, 10.0)
        return hits, launches, saved, wasted

    def ev_policy(alpha, temps=None):
        def pol(p, tool_time, think):
            probs = scaled(p["probs"], temps[p["k"] % 2]) if temps else p["probs"]
            out = []
            for cmd, pr in sorted(probs.items(), key=lambda kv: -kv[1]):
                t = tool_time.get(cmd, 10.0)
                if pr * min(t, think or 6.0) - (1 - pr) * alpha * t > 0 and len(out) < 2:
                    out.append(cmd)
            return out
        return pol

    def top1(p, *_):
        return [max(p["probs"], key=p["probs"].get)] if p["probs"] else []

    def thresh(x):
        return lambda p, *_: [c for c, pr in p["probs"].items() if pr > x][:2]

    def oracle(p, *_):
        return [p["actual"]] if p["actual"] and classify(p["actual"], cwd) else []

    n_wait = [c for c in calls if c["tool"] == "Bash"]
    return finish(a, race, calls, wall, pred, predictions, simulate, ev_policy, top1, thresh, oracle, n_wait,
                  "shell commands", "guesses are thrown away at the next edit or unrecognized command")


# ---------------------------------------------------------------------------
def load_tools(race, calls):
    """Tool schemas: the proxy's dump if the race had one, else a rough inference from the calls."""
    import mcp_proxy as mp
    path = os.path.join(race, "jevsight-data", "tools.json")
    try:
        d = json.load(open(path))
        tools = {t["name"]: t for t in d["tools"]}
        return tools, set(d.get("read_only") or mp.READ_ONLY), "from %s" % os.path.relpath(path, race)
    except (OSError, ValueError, KeyError):
        pass
    tools = {}
    for c in calls:
        if not c["tool"].startswith("mcp__"):
            continue
        short = c["tool"].split("__", 2)[-1]
        inp = c["input"]
        wrapped = isinstance(inp.get("params"), dict)
        inner = inp["params"] if wrapped else inp
        t = tools.setdefault(short, {"name": short, "_keys": [], "_wrapped": wrapped})
        t["_keys"].append(set(inner))
    for t in tools.values():
        keys = set().union(*t["_keys"]) if t["_keys"] else set()
        req = sorted(set.intersection(*t["_keys"])) if t["_keys"] else []
        inner = {"type": "object", "properties": {k: {"type": "string"} for k in sorted(keys)}, "required": req}
        t["inputSchema"] = {"type": "object", "properties": {"params": inner}, "required": ["params"]} if t.pop("_wrapped") else inner
        t.pop("_keys")
    return tools, set(mp.READ_ONLY), "inferred from the trajectory (no tools.json; required = args present in every call)"


def run_mcp(a, race, calls, wall, pred, cache, cache_path):
    import mcp_proxy as mp
    from predictor import render_state

    tools, read_only, tools_src = load_tools(race, calls)
    prompt = a.prompt
    if not prompt:
        try:
            prompt = open(os.path.join(race, "prompt.txt")).read()
        except OSError:
            prompt = ""

    def short(name):
        return name.split("__", 2)[-1] if name.startswith("mcp__") else name

    def key_of(c):
        s = short(c["tool"])
        return mp.call_key(s, c["input"], tools.get(s))

    from narration import narration_step, n_tool_steps, trace_steps
    steps, steps_full, predictions = [], [], []
    values, gens, used_args, called, default_branch = {}, {}, {}, set(), {}
    if prompt:
        mp.extract_values(values, prompt, gens, 0)   # same seeding as the proxy
    print("Replaying %d tool calls from %s/%s through %s (schemas %s) ..." % (
        len(calls), os.path.basename(race), a.side, pred.name, tools_src))
    for k, c in enumerate(calls):
        s = short(c["tool"])
        args, text = c["input"], c["text"]
        for kk, v in mp.unwrap(args).items():
            if isinstance(v, (str, int, float, bool)):
                lst = used_args.setdefault(kk, [])
                if v in lst:
                    lst.remove(v)
                lst.append(v)
        key = key_of(c)
        called.add(key)
        alt = mp.alias_args(tools.get(s), args, default_branch)
        if alt is not None:
            called.add(mp.call_key(s, alt, tools.get(s)))
        mp.extract_values(values, text, gens, k + 1)
        if s == "describe_project":
            mp.learn_default_branch(default_branch, text, mp.unwrap(args).get("projectId"))
        steps.append(mp.step_line(s, args, text))
        steps_full.append(mp.step_line(s, args, text, mp.FULL_RESULT_CHARS))
        if k + 1 >= len(calls):
            break
        cands = mp.build_candidates(tools, read_only, values, used_args, called, gens, last_tool=s)
        keys = [kk for kk, _, _ in cands]
        sections = [("TOOLS ON THIS MCP SERVER (name(required args) [may it be run early]: what it does):",
                     mp.tool_catalog(tools, read_only))]
        nxt = calls[k + 1]
        ns = short(nxt["tool"])
        actual = key_of(nxt) if nxt["tool"].startswith("mcp__") else None
        actual_alias = None
        if actual is not None:
            alt = mp.alias_args(tools.get(ns), nxt["input"], default_branch)
            actual_alias = mp.call_key(ns, alt, tools.get(ns)) if alt is not None else None
        actual_safe = actual is not None and mp.is_safe(ns, read_only)

        def record(stage, t_ready):
            facts = {"tool_calls_so_far": n_tool_steps(steps),
                     "ids_seen_so_far": ", ".join(sorted({v for vs in values.values() for v in vs[:3]}))[:600]}
            state = render_state(prompt, trace_steps(steps[-200:], steps_full[-200:]), facts, sections)
            ck = hashlib.sha1((pred.name + "mcp" + state + "\x00".join(keys)).encode()).hexdigest()
            probs = ask(pred, cache, cache_path, ck, lambda: pred.predict_generic(
                state, mp.ACTIONS, "call_tool", keys, mp.ACTION_INSTR, mp.CHOICE_INSTR), k) if keys else {"p_run": 0.0, "commands": {}}
            predictions.append({"k": k, "stage": stage, "t_ready": t_ready, "probs": probs.get("commands", {}),
                                "p_run": probs.get("p_run", 0.0), "actual": actual if actual_safe else None,
                                "actual_raw": actual, "next_tool": nxt["tool"],
                                "hit_key": (lambda kk, a1=actual, a2=actual_alias: kk == a1 or (a2 is not None and kk == a2))})

        record("result", c["t_result"] + a.latency)   # right after the result, as the live proxy does
        if a.narration and c["narration"]:            # and again once Claude has narrated its next move
            for _tt, txt in c["narration"]:
                steps.append(narration_step(txt))
                steps_full.append(narration_step(txt))
            record("narration", max((tt if tt is not None else c["t_result"]) for tt, _ in c["narration"]) + a.latency)
        if (k + 1) % 10 == 0:
            print("  %d/%d steps" % (k + 1, len(calls) - 1))

    def simulate(policy):
        jobs, tool_time, think = {}, {}, None   # jobs: key -> (start, tool name)
        hits = launches = 0
        saved = wasted = 0.0
        last_result = None
        by_k = {}
        for p in predictions:   # one prediction per step, or two when Claude narrated (result, then narration)
            by_k.setdefault(p["k"], []).append(p)
        for k, c in enumerate(calls):
            now_call = c["t_call"]
            if last_result is not None:
                think = (now_call - last_result) if think is None else 0.7 * think + 0.3 * (now_call - last_result)
            dur = c["t_result"] - c["t_call"]
            if c["tool"].startswith("mcp__"):
                s = short(c["tool"])
                key = key_of(c)
                alt = mp.alias_args(tools.get(s), c["input"], default_branch)
                alt_key = mp.call_key(s, alt, tools.get(s)) if alt is not None else None
                hit = key if key in jobs else (alt_key if alt_key in jobs else None)
                if hit is not None:
                    start, _ = jobs.pop(hit)
                    hits += 1
                    saved += max(0.0, min(dur, now_call - start))
                tool_time[s] = dur if s not in tool_time else 0.7 * tool_time[s] + 0.3 * dur
                if not mp.is_safe(s, read_only):   # a write: every saved result is thrown away
                    for j, (st, jn) in jobs.items():
                        wasted += min(tool_time.get(jn, 1.0), max(0.0, now_call - st))
                    jobs.clear()
            last_result = c["t_result"]
            for p, cmd in [(p, cmd) for p in by_k.get(k, []) for cmd in policy(p, tool_time, think)]:
                if cmd not in jobs:
                    jobs[cmd] = (p["t_ready"], cmd.split(" ", 1)[0])
                    launches += 1
        for j, (st, jn) in jobs.items():
            wasted += tool_time.get(jn, 1.0)
        return hits, launches, saved, wasted

    def ev_policy(alpha, temps=None):
        def pol(p, tool_time, think):
            probs = scaled(p["probs"], temps[p["k"] % 2]) if temps else p["probs"]
            out = []
            for cmd, pr in sorted(probs.items(), key=lambda kv: -kv[1]):
                t = tool_time.get(cmd.split(" ", 1)[0], 1.0)
                if pr * min(t, think if think is not None else 3.0) - (1 - pr) * alpha * t > 0 and len(out) < 2:
                    out.append(cmd)
            return out
        return pol

    def top1(p, *_):
        return [max(p["probs"], key=p["probs"].get)] if p["probs"] else []

    def thresh(x):
        return lambda p, *_: [c for c, pr in p["probs"].items() if pr > x][:2]

    def oracle(p, *_):
        return [p["actual"]] if p["actual"] else []

    n_wait = [c for c in calls if c["tool"].startswith("mcp__")]
    return finish(a, race, calls, wall, pred, predictions, simulate, ev_policy, top1, thresh, oracle, n_wait,
                  "MCP calls", "guesses are thrown away at the next non-read-only call (a write, run_sql, or a secret)")


# ---------------------------------------------------------------------------
def finish(a, race, calls, wall, pred, predictions, simulate, ev_policy, top1, thresh, oracle, waited_calls, unit, waste_note):
    def top_of(p):
        return max(p["probs"], key=p["probs"].get) if p["probs"] else None

    all_predictions = predictions
    final = {}
    for p in predictions:
        final[p["k"]] = p          # the prediction the live system acted on last: after narration when there was some
    predictions = list(final.values())
    temps = cross_fit_temperatures(predictions, top_of)
    policies = [("never", lambda *_: []), ("always top-1", top1), ("p > 0.5", thresh(0.5)),
                ("EV gate a=%.2f" % a.alpha, ev_policy(a.alpha)), ("EV gate a=1.00", ev_policy(1.0)),
                ("EV gate a=%.2f, temperature-scaled" % a.alpha, ev_policy(a.alpha, temps)),
                ("perfect predictor (ceiling)", oracle)]
    wait = sum(c["t_result"] - c["t_call"] for c in waited_calls)
    lines = ["# Replay benchmark: %s (%s side, predictor: %s)" % (os.path.basename(race), a.side, pred.name), ""]
    lines.append("Recorded run: %.1fs wall, %d tool calls, %d %s, %.1fs waiting on them (%.1f%% of wall)." % (
        wall or 0, len(calls), len(waited_calls), unit, wait, 100 * wait / wall if wall else 0))
    lines.append("")
    lines.append("| policy | launches | hits | time saved | projected wall | faster by | background waste |")
    lines.append("|---|---|---|---|---|---|---|")
    for name, pol in policies:
        h, la, sv, wa = simulate(pol)
        lines.append("| %s | %d | %d | %.1fs | %.1fs | %.1f%% | %.1fs |" % (
            name, la, h, sv, (wall or 0) - sv, 100 * sv / wall if wall else 0, wa))
    run_pairs = [(p["p_run"], 1 if p["actual_raw" if "actual_raw" in p else "actual"] is not None else 0) for p in predictions]
    top_pairs, top_pairs_scaled = [], []
    for p in predictions:
        top = top_of(p)
        if top is not None:
            y = 1 if p["hit_key"](top) else 0
            top_pairs.append((p["probs"][top], y))
            top_pairs_scaled.append((scaled({top: p["probs"][top]}, temps[p["k"] % 2])[top], y))
    e1, _ = ece(run_pairs)
    e2, rows = ece(top_pairs)
    e3, rows_scaled = ece(top_pairs_scaled)
    cmd_steps = [p for p in predictions if p["actual"]]
    acc = sum(1 for p in cmd_steps if top_of(p) and p["hit_key"](top_of(p))) / len(cmd_steps) if cmd_steps else None
    lines.append("")
    lines.append("Prediction quality on this trajectory: P(next is a %s) Brier %.3f, ECE %.3f (actual rate %.2f, mean predicted %.2f); "
                 "top-1 accuracy %s over %d speculable steps; top-choice ECE %.3f raw, %.3f after temperature scaling." % (
                     unit.rstrip("s"), brier(run_pairs) or 0, e1 or 0, sum(y for _, y in run_pairs) / max(1, len(run_pairs)),
                     sum(p for p, _ in run_pairs) / max(1, len(run_pairs)),
                     ("%.2f" % acc) if acc is not None else "n/a", len(cmd_steps), e2 or 0, e3 or 0))
    narr = [p for p in all_predictions if p.get("stage") == "narration" and p["actual"]]
    if narr:
        ks = {p["k"] for p in narr}
        before = [p for p in all_predictions if p.get("stage") == "result" and p["k"] in ks]
        acc_b = sum(1 for p in before if top_of(p) and p["hit_key"](top_of(p))) / len(before)
        acc_n = sum(1 for p in narr if top_of(p) and p["hit_key"](top_of(p))) / len(narr)
        lead = [calls[i + 1]["t_call"] - max(tt for tt, _ in c["narration"]) for i, c in enumerate(calls[:-1])
                if c.get("narration") and all(tt is not None for tt, _ in c["narration"])]
        lines.append("")
        lines.append("Claude's narration: %d of %d speculable steps had it before the next call (arriving %.2fs before the call on average); "
                     "top-1 accuracy on those steps %.2f from the result alone vs %.2f after the narration." % (
                         len(narr), len(cmd_steps), sum(lead) / len(lead) if lead else 0, acc_b, acc_n))
    lines.append("")
    lines.append("Reliability of the top choice (raw):")
    lines.append("| predicted | n | mean p | was next |")
    lines.append("|---|---|---|---|")
    for b, n, mp_, act in rows:
        lines.append("| %s | %d | %.2f | %.2f |" % (b, n, mp_, act))
    lines.append("")
    if temps[0] == 1.0 and temps[1] == 1.0:
        lines.append("Temperature scaling: skipped, fewer than %d speculable steps per fold (the scaled row equals the raw EV gate)." % MIN_CALIB_STEPS)
    else:
        lines.append("Temperature scaling (a finding, not a fix in the plugin): T fitted by log loss on the top choice, "
                     "two folds by step parity, each step scored with the other fold's T: T=%.1f (even steps), T=%.1f (odd steps). "
                     "T>1 means Jev was overconfident on this run." % (temps[0], temps[1]))
    lines.append("")
    lines.append("Assumptions: guesses start %.1fs after each tool result (prediction latency); %s; "
                 "waste counts each thrown-away guess up to its expected run time." % (a.latency, waste_note))
    text = "\n".join(lines)
    print()
    print(text)
    if a.md:
        open(a.md, "w").write(text)


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("race")
    ap.add_argument("--side", default="baseline")
    ap.add_argument("--mode", choices=["auto", "bash", "mcp"], default="auto")
    ap.add_argument("--prompt", help="task prompt shown to Jev (default: <race>/prompt.txt, or the fix-app prompt)")
    ap.add_argument("--predictor", choices=["jev", "heuristic"], default="jev")
    ap.add_argument("--alpha", type=float, default=0.25)
    ap.add_argument("--latency", type=float, default=0.4, help="assumed live prediction latency, seconds")
    ap.add_argument("--no-narration", dest="narration", action="store_false",
                    help="predict without Claude's narration between calls (the state Jevsight used before)")
    ap.add_argument("--md")
    a = ap.parse_args()
    if a.predictor == "heuristic":
        os.environ["JEVSIGHT_PREDICTOR"] = "heuristic"
    os.environ.setdefault("JEVSIGHT_RETRY_BUDGET", "20")
    from predictor import make_predictor

    race = os.path.expanduser(a.race.rstrip("/"))
    calls, wall = trajectory(race, a.side)
    if a.mode == "auto":
        a.mode = "mcp" if any(c["tool"].startswith("mcp__") for c in calls) else "bash"
    cache_path = os.path.join(race, "replay_cache.json")
    try:
        cache = json.load(open(cache_path))
    except (OSError, ValueError):
        cache = {}
    pred = make_predictor()
    if a.mode == "mcp":
        run_mcp(a, race, calls, wall, pred, cache, cache_path)
    else:
        run_bash(a, race, calls, wall, pred, cache, cache_path)


if __name__ == "__main__":
    main()

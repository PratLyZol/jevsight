#!/usr/bin/env python3
"""Benchmark Jevsight races from their logs.

Usage: python3 eval/bench.py ~/jevsight-races/race-*   [--md report.md]

For each race it reports:
  1. Where the time went on each side (model time vs everything else).
  2. How good Jev's predictions were: accuracy, Brier score, calibration.
  3. What speculation actually did: launches, hits, waste.
  4. A counterfactual: how different launch policies would have done on the
     same recorded steps (Jev's probabilities never change, only the rule).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

_ENV = re.compile(r"^(?:[A-Z_][A-Z0-9_]*=\S*\s+)+")
_SUFFIX = [re.compile(r"\s+2>&1$"), re.compile(r"\s*\|\s*(head|tail)(\s+-n)?\s+-?\d+$")]
_CD = re.compile(r"^cd\s+\S+\s*&&\s*(.+)$")


def canon(cmd):
    """Same command for speculation purposes: drop env prefixes, a leading cd, 2>&1 and | tail/head."""
    c = " ".join((cmd or "").split())
    m = _CD.match(c)
    if m:
        c = m.group(1)
    c = _ENV.sub("", c)
    changed = True
    while changed:
        changed = False
        for rx in _SUFFIX:
            n = rx.sub("", c)
            if n != c:
                c, changed = n, True
    return c.strip()


def load_jsonl(path):
    out = []
    if not os.path.exists(path):
        return out
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("{"):
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    return out


def load_times(path):
    t = {}
    for r in load_jsonl(path):
        t[r["line"]] = r["t"]
    return t


def mcp_key(name, args):
    """Canonical key for an MCP call, same shape as the proxy's call_key: short tool name + sorted JSON args."""
    short = name.split("__", 2)[-1] if name.startswith("mcp__") else name
    return "%s %s" % (short, json.dumps(args or {}, sort_keys=True, separators=(",", ":")))


def side_stats(stream, times=None):
    """Per-side numbers from the stream-json log. Shell commands (Bash) and MCP tool calls (mcp__*)
    are both tracked as waits: the time from Claude issuing the call to its result arriving."""
    tools, bash, mcp = {}, [], []
    result = None
    pending, waits, mcp_waits = {}, [], []
    times = times or {}
    for i, ev in enumerate(stream):
        now = times.get(i)
        if ev.get("type") == "user" and now is not None:
            for c in (ev.get("message") or {}).get("content") or []:
                if c.get("type") == "tool_result" and c.get("tool_use_id") in pending:
                    cmd, t0, kind = pending.pop(c["tool_use_id"])
                    (waits if kind == "bash" else mcp_waits).append((canon(cmd) if kind == "bash" else cmd, round(now - t0, 2)))
        if ev.get("type") == "assistant":
            for c in (ev.get("message") or {}).get("content") or []:
                if c.get("type") == "tool_use":
                    name = c.get("name") or ""
                    tools[name] = tools.get(name, 0) + 1
                    if name == "Bash":
                        bash.append((c.get("input") or {}).get("command", ""))
                        if now is not None:
                            pending[c.get("id")] = (bash[-1], now, "bash")
                    elif name.startswith("mcp__"):
                        mcp.append(mcp_key(name, c.get("input") or {}))
                        if now is not None:
                            pending[c.get("id")] = (mcp[-1], now, "mcp")
        elif ev.get("type") == "result":
            result = ev
    r = result or {}
    wall = (r.get("duration_ms") or 0) / 1000
    api = (r.get("duration_api_ms") or 0) / 1000
    mcp_total = sum(w for _, w in mcp_waits) if mcp_waits else None
    return {
        "finished": result is not None,
        "wall_s": wall, "model_s": api, "other_s": max(0.0, wall - api),
        "turns": r.get("num_turns"), "cost_usd": r.get("total_cost_usd"),
        "tools": tools, "bash": bash, "waits": waits,
        "wait_total_s": sum(w for _, w in waits) if waits else None,
        "mcp": mcp, "mcp_waits": mcp_waits, "mcp_wait_total_s": mcp_total,
        "mcp_wait_share": (mcp_total / wall) if (mcp_total is not None and wall) else None,
    }


def brier(pairs):
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs) if pairs else None


def ece(pairs, bins=10):
    if not pairs:
        return None, []
    b = [[0, 0.0, 0] for _ in range(bins)]
    for p, y in pairs:
        i = min(int(p * bins), bins - 1)
        b[i][0] += 1
        b[i][1] += p
        b[i][2] += y
    total = len(pairs)
    e = sum(abs(x[1] / x[0] - x[2] / x[0]) * x[0] / total for x in b if x[0])
    rows = [("%.1f-%.1f" % (i / bins, (i + 1) / bins), x[0], x[1] / x[0], x[2] / x[0]) for i, x in enumerate(b) if x[0]]
    return e, rows


def jev_stats(events):
    preds = {e["pred"]: e for e in events if e.get("type") == "predict"}
    outs = [e for e in events if e.get("type") == "outcome"]
    errors = [e for e in events if e.get("type") == "predict_error"]
    steps = []
    for o in outs:
        p = preds.get(o.get("pred"))
        if not p:
            continue
        probs = o.get("probs") or {}
        actual = canon(o.get("actual_cmd") or "") if o.get("actual_cmd") else None
        pc = {}
        for k, v in probs.items():
            pc[canon(k)] = pc.get(canon(k), 0.0) + v
        top = max(pc, key=pc.get) if pc else None
        steps.append({
            "t_pred": p["ts"] - p.get("latency_s", 0), "t_out": o["ts"],
            "think_s": max(0.0, o["ts"] - (p["ts"] - p.get("latency_s", 0))),
            "p_run": o.get("p_run", 0.0), "is_run": o.get("actual_kind") == "run_command",
            "actual": actual, "p_actual": pc.get(actual, 0.0) if actual else 0.0,
            "top": top, "p_top": pc.get(top, 0.0) if top else 0.0, "kind": o.get("actual_kind"),
            "probs": pc,
        })
    lat = sorted(p.get("latency_s", 0) for p in preds.values())
    run_pairs = [(s["p_run"], 1 if s["is_run"] else 0) for s in steps]
    cmd_steps = [s for s in steps if s["is_run"]]
    top_pairs = [(s["p_top"], 1 if (s["actual"] == s["top"]) else 0) for s in steps if s["top"]]
    e_run, rows_run = ece(run_pairs)
    e_top, rows_top = ece(top_pairs)
    return {
        "predictions": len(preds), "errors": len(errors),
        "error_rate": len(errors) / max(1, len(errors) + len(preds)),
        "latency_p50": lat[len(lat) // 2] if lat else None,
        "latency_p90": lat[int(len(lat) * 0.9)] if lat else None,
        "steps": steps, "n_steps": len(steps),
        "base_rate_run": sum(y for _, y in run_pairs) / len(run_pairs) if run_pairs else None,
        "mean_p_run": sum(p for p, _ in run_pairs) / len(run_pairs) if run_pairs else None,
        "brier_run": brier(run_pairs), "ece_run": e_run, "rel_run": rows_run,
        "top1_cmd_acc": (sum(1 for s in cmd_steps if s["top"] == s["actual"]) / len(cmd_steps)) if cmd_steps else None,
        "cmd_steps": len(cmd_steps),
        "ece_top": e_top, "rel_top": rows_top,
    }


def spec_stats(events):
    c = lambda t: [e for e in events if e.get("type") == t]  # noqa: E731
    done = {e["job"]: e for e in c("job_done")}
    used = {e["job"] for e in c("hit")}
    durs = {}
    for e in done.values():
        durs.setdefault(canon(e["cmd"]), []).append(e["dur_s"])
    wasted = sum(e["dur_s"] for j, e in done.items() if j not in used and e.get("status") == "done")
    wasted += sum(e.get("wasted_s", 0) for e in c("wasted"))
    return {
        "launches": len(c("launch")), "hits": len(c("hit")), "misses": len(c("miss")),
        "saved_s": sum(e.get("saved_s", 0) for e in c("saved")), "wasted_s": wasted,
        "cmd_durations": {k: sum(v) / len(v) for k, v in durs.items()},
    }


def policies(steps, durations, default_dur=15.0):
    """Replay launch rules on recorded steps. A launch on step s runs the top command
    (canon). Hit if the agent's next call is that command. Saved = min(dur, think).
    Wasted = dur for a miss. Ignores version invalidation (optimistic for all rules alike)."""
    rules = {
        "never": lambda s: False,
        "always top-1": lambda s: s["top"] is not None,
        "p_top > 0.5": lambda s: s["p_top"] > 0.5,
        "p_top > 0.9": lambda s: s["p_top"] > 0.9,
    }
    for alpha in (0.25, 1.0):
        def ev_rule(s, a=alpha):
            t = durations.get(s["top"], default_dur)
            return s["top"] is not None and s["p_top"] * min(t, 6.0) - (1 - s["p_top"]) * a * t > 0
        rules["EV gate a=%.2f" % alpha] = ev_rule
    rows = []
    for name, rule in rules.items():
        launches = hits = 0
        saved = wasted = 0.0
        for s in steps:
            if not rule(s):
                continue
            launches += 1
            dur = durations.get(s["top"], default_dur)
            if s["actual"] == s["top"]:
                hits += 1
                saved += min(dur, s["think_s"])
            else:
                wasted += dur
        rows.append((name, launches, hits, saved, wasted))
    oracle = sum(min(durations.get(s["actual"], default_dur), s["think_s"]) for s in steps if s["is_run"] and s["actual"] in durations)
    return rows, oracle


def fmt(x, nd=2, suffix=""):
    return "n/a" if x is None else ("%." + str(nd) + "f%s") % (x, suffix)


def report(race):
    name = os.path.basename(race.rstrip("/"))
    base = side_stats(load_jsonl(os.path.join(race, "baseline.stream.jsonl")), load_times(os.path.join(race, "baseline.times.jsonl")))
    jev = side_stats(load_jsonl(os.path.join(race, "jevsight.stream.jsonl")), load_times(os.path.join(race, "jevsight.times.jsonl")))
    events = load_jsonl(os.path.join(race, "jevsight-data", "events.jsonl"))
    js, sp = jev_stats(events), spec_stats(events)
    L = ["## %s" % name, ""]
    L.append("### 1. Where the time went")
    L.append("| | finished | wall | model time | everything else | turns | cost | shell cmds | MCP calls |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for n, s in (("baseline", base), ("jevsight", jev)):
        share = (100 * s["model_s"] / s["wall_s"]) if s["wall_s"] else None
        L.append("| %s | %s | %s | %s (%s) | %s | %s | %s | %d | %d |" % (
            n, "yes" if s["finished"] else "no (cut off)", fmt(s["wall_s"], 1, "s"), fmt(s["model_s"], 1, "s"),
            fmt(share, 1, "%"), fmt(s["other_s"], 1, "s"), s["turns"] or "n/a",
            ("$%.2f" % s["cost_usd"]) if s["cost_usd"] else "n/a", len(s["bash"]), len(s["mcp"])))
    if base["mcp_waits"] or jev["mcp_waits"]:
        L.append("")
        L.append("Waiting on MCP calls (from per-line timestamps):")
        L.append("| | calls | total wait | mean wait | share of wall |")
        L.append("|---|---|---|---|---|")
        for n, s in (("baseline", base), ("jevsight", jev)):
            if s["mcp_waits"]:
                L.append("| %s | %d | %.1fs | %.1fs | %s |" % (n, len(s["mcp_waits"]), s["mcp_wait_total_s"],
                                                             s["mcp_wait_total_s"] / len(s["mcp_waits"]),
                                                             fmt(100 * s["mcp_wait_share"] if s["mcp_wait_share"] is not None else None, 1, "%")))
        fast = [w for _, w in jev["mcp_waits"] if w < 1.0]
        if jev["mcp_waits"]:
            L.append("")
            L.append("jevsight side: %d of %d MCP calls answered in under 1s." % (len(fast), len(jev["mcp_waits"])))
    if base["waits"] or jev["waits"]:
        L.append("")
        L.append("Waiting on shell commands (from per-line timestamps):")
        L.append("| | commands | total wait | mean wait |")
        L.append("|---|---|---|---|")
        for n, s in (("baseline", base), ("jevsight", jev)):
            if s["waits"]:
                L.append("| %s | %d | %.1fs | %.1fs |" % (n, len(s["waits"]), s["wait_total_s"], s["wait_total_s"] / len(s["waits"])))
    if base["finished"]:
        L.append("")
        L.append("Ceiling: Jevsight can only hide non-model time. Here that is at most %s of the baseline's %s wall time (%s)." % (
            fmt(base["other_s"], 1, "s"), fmt(base["wall_s"], 1, "s"),
            fmt(100 * base["other_s"] / base["wall_s"] if base["wall_s"] else None, 1, "%")))
    L.append("")
    L.append("### 2. Jev as a predictor")
    L.append("- predictions: %d, upstream errors: %d (%s of calls)" % (js["predictions"], js["errors"], fmt(100 * js["error_rate"], 0, "%")))
    L.append("- latency: p50 %s, p90 %s" % (fmt(js["latency_p50"], 2, "s"), fmt(js["latency_p90"], 2, "s")))
    unit = "tool call" if (base["mcp"] or jev["mcp"]) else "shell command"
    L.append("- steps with a prediction and a known outcome: %d (next step was a %s in %d)" % (js["n_steps"], unit, js["cmd_steps"]))
    L.append("- P(next step is a %s): Jev's average %s vs actual rate %s; Brier %s; ECE %s" % (
        unit, fmt(js["mean_p_run"]), fmt(js["base_rate_run"]), fmt(js["brier_run"], 3), fmt(js["ece_run"], 3)))
    L.append("- top-1 accuracy when the next step was a %s: %s (top-choice ECE %s over %d steps)" % (
        unit, fmt(js["top1_cmd_acc"]), fmt(js["ece_top"], 3), len(js["rel_top"]) and sum(r[1] for r in js["rel_top"])))
    L.append("")
    L.append("Reliability of P(next step is a %s):" % unit)
    L.append("| Jev said | n | mean p | actually happened |")
    L.append("|---|---|---|---|")
    for b, n, mp, act in js["rel_run"]:
        L.append("| %s | %d | %.2f | %.2f |" % (b, n, mp, act))
    L.append("")
    L.append("Reliability of the top choice (P(this exact call is next) vs how often it was):")
    L.append("| Jev said | n | mean p | was next |")
    L.append("|---|---|---|---|")
    for b, n, mp, act in js["rel_top"]:
        L.append("| %s | %d | %.2f | %.2f |" % (b, n, mp, act))
    L.append("")
    L.append("### 3. What speculation did")
    L.append("- launches %d, hits %d, misses on speculable commands %d, time saved %s, background time wasted %s" % (
        sp["launches"], sp["hits"], sp["misses"], fmt(sp["saved_s"], 1, "s"), fmt(sp["wasted_s"], 1, "s")))
    L.append("- measured command times: %s" % ", ".join("%s %.1fs" % (k, v) for k, v in sp["cmd_durations"].items()) or "none")
    L.append("")
    rows, oracle = policies(js["steps"], sp["cmd_durations"])
    L.append("### 4. Counterfactual: same steps, different launch rules")
    L.append("Shell commands are matched ignoring env prefixes and `2>&1 | tail` suffixes; MCP calls by tool name + arguments.")
    L.append("")
    L.append("| rule | launches | hits | time saved | background waste |")
    L.append("|---|---|---|---|---|")
    for name_, la, hi, sv, wa in rows:
        L.append("| %s | %d | %d | %.1fs | %.1fs |" % (name_, la, hi, sv, wa))
    L.append("| perfect predictor (ceiling) | | | %.1fs | 0s |" % oracle)
    L.append("")
    return "\n".join(L), {"base": base, "jev": jev, "js": {k: v for k, v in js.items() if k != "steps"}, "sp": sp,
                          "policies": rows, "oracle": oracle}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("races", nargs="+")
    ap.add_argument("--md")
    ap.add_argument("--json")
    a = ap.parse_args()
    races = [r for pat in a.races for r in sorted(glob.glob(os.path.expanduser(pat))) if os.path.isdir(r)]
    parts, data = ["# Jevsight race benchmark", ""], {}
    for r in races:
        md, d = report(r)
        parts.append(md)
        data[os.path.basename(r.rstrip("/"))] = d
    text = "\n".join(parts)
    print(text)
    if a.md:
        open(a.md, "w").write(text)
    if a.json:
        json.dump(data, open(a.json, "w"), indent=2, default=str)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Measure the speculation ceiling for MCP tool calls (e.g. the Neon MCP server).

Runs ONE plain Claude Code session (your normal config, where Neon is connected)
on a read-only exploration task, records every event with a timestamp, then
computes what a perfect next-call predictor could have hidden:
for each read-only MCP call, min(call duration, idle time before Claude issued it).

Usage:
  python3 eval/mcp_probe.py                         # run the probe + report
  python3 eval/mcp_probe.py --report DIR            # re-report an existing probe
  python3 eval/mcp_probe.py --server Neon --prompt "..."
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time

DEFAULT_PROMPT = (
    "Using only the Neon MCP tools, list my Neon projects, pick the project with the most tables, and write a short "
    "report of its schema: every table, its columns and types, and an approximate row count for each table. "
    "This is read-only: do not create, modify or delete anything."
)
# Never counted as speculable: they write, cost money, or return secrets.
UNSAFE = re.compile(r"(create|delete|reset|update|provision|prepare|complete|migration|connection_string|run_sql_transaction)", re.I)


def run_probe(a, outdir):
    os.makedirs(outdir, exist_ok=True)
    cmd = ["claude", "-p", a.prompt, "--output-format", "stream-json", "--verbose",
           "--allowedTools", "mcp__%s" % a.server, "--disallowedTools", "Bash Agent Task Edit Write"]
    if a.model:
        cmd += ["--model", a.model]
    print("running probe in %s ..." % outdir)
    t0 = time.time()
    with open(os.path.join(outdir, "probe.stream.jsonl"), "w") as log, \
            open(os.path.join(outdir, "probe.times.jsonl"), "w") as tl:
        p = subprocess.Popen(cmd, cwd=outdir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for n, line in enumerate(p.stdout):
            log.write(line)
            tl.write(json.dumps({"line": n, "t": round(time.time() - t0, 3)}) + "\n")
            try:
                ev = json.loads(line)
                if ev.get("type") == "assistant":
                    for c in ev["message"].get("content", []):
                        if c.get("type") == "tool_use":
                            print("  %6.1fs  %s %s" % (time.time() - t0, c["name"], json.dumps(c.get("input"))[:90]))
            except (ValueError, KeyError):
                pass
        p.wait()


def report(outdir, server):
    lines = [json.loads(l) for l in open(os.path.join(outdir, "probe.stream.jsonl")) if l.strip().startswith("{")]
    times = {}
    for l in open(os.path.join(outdir, "probe.times.jsonl")):
        r = json.loads(l)
        times[r["line"]] = r["t"]
    calls, by_id, wall = [], {}, None
    for i, ev in enumerate(lines):
        t = times.get(i)
        if ev.get("type") == "assistant" and ev.get("parent_tool_use_id") is None:
            for c in ev["message"].get("content", []):
                if c.get("type") == "tool_use":
                    rec = {"name": c["name"], "input": c.get("input") or {}, "t_call": t, "t_result": None}
                    by_id[c["id"]] = rec
                    calls.append(rec)
        elif ev.get("type") == "user":
            for c in ev["message"].get("content", []):
                if c.get("type") == "tool_result" and c.get("tool_use_id") in by_id:
                    by_id[c["tool_use_id"]]["t_result"] = t
        elif ev.get("type") == "result":
            wall = (ev.get("duration_ms") or 0) / 1000 or t
    calls = [c for c in calls if c["t_result"] is not None]
    prefix = "mcp__%s__" % server
    prev_result, rows, ceiling, mcp_time = None, [], 0.0, 0.0
    for c in calls:
        dur = c["t_result"] - c["t_call"]
        idle = max(0.0, c["t_call"] - prev_result) if prev_result is not None else 0.0
        is_mcp = c["name"].startswith(prefix)
        tool = c["name"][len(prefix):] if is_mcp else c["name"]
        safe = is_mcp and not UNSAFE.search(tool) and not (tool == "run_sql" and not re.match(
            r"\s*(select|with|explain|show)\b", str(c["input"].get("sql", "")), re.I))
        hide = min(dur, idle) if safe else 0.0
        if is_mcp:
            mcp_time += dur
        ceiling += hide
        rows.append((c["t_call"], idle, dur, "yes" if safe else "no", tool, json.dumps(c["input"])[:70], hide))
        prev_result = c["t_result"]
    out = ["# MCP speculation ceiling (%s)" % os.path.basename(outdir), ""]
    out.append("| t | idle before | call time | speculable | tool | args | hideable |")
    out.append("|---|---|---|---|---|---|---|")
    for r in rows:
        out.append("| %.1fs | %.1fs | %.1fs | %s | %s | `%s` | %.1fs |" % r)
    out.append("")
    wall = wall or (calls[-1]["t_result"] if calls else 0)
    out.append("Wall %.1fs; %d tool calls; %.1fs inside %s MCP calls (%.0f%% of wall)." % (
        wall, len(calls), mcp_time, server, 100 * mcp_time / wall if wall else 0))
    out.append("**Perfect-predictor ceiling: %.1fs hideable = %.1f%% of wall.** "
               "Hideable = min(call time, Claude's idle time before the call), read-only calls only." % (
                   ceiling, 100 * ceiling / wall if wall else 0))
    text = "\n".join(out)
    print(text)
    open(os.path.join(outdir, "ceiling.md"), "w").write(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="Neon", help="MCP server name as Claude Code shows it (tools are mcp__<server>__*)")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--model")
    ap.add_argument("--report", help="re-report an existing probe directory")
    a = ap.parse_args()
    if a.report:
        report(os.path.expanduser(a.report), a.server)
        return
    outdir = os.path.expanduser("~/jevsight-races/mcp-probe-%s" % time.strftime("%Y%m%d-%H%M%S"))
    run_probe(a, outdir)
    report(outdir, a.server)


if __name__ == "__main__":
    main()

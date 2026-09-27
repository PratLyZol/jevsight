#!/usr/bin/env python3
"""Summarize Jevsight events: hits, misses, time saved, time wasted, calibration.

Usage: stats.py [--cwd PATH] [--session ID] [--since EPOCH] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import events_path  # noqa: E402


def load(path, cwd=None, session=None, since=None):
    out = []
    try:
        with open(path) as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if cwd and e.get("cwd") and not str(e.get("cwd")).startswith(cwd):
                    continue
                if session and e.get("session") and e.get("session") != session:
                    continue
                if since and e.get("ts", 0) < since:
                    continue
                out.append(e)
    except OSError:
        pass
    return out


def summarize(events):
    c = lambda t: [e for e in events if e.get("type") == t]  # noqa: E731
    preds, outcomes = c("predict"), c("outcome")
    hits, misses = c("hit"), c("miss")
    saved = sum(e.get("saved_s", 0) for e in c("saved"))
    done = c("job_done")
    used = {e.get("job") for e in hits}
    wasted = sum(e.get("dur_s", 0) for e in done if e.get("job") not in used)
    wasted += sum(e.get("wasted_s", 0) for e in c("wasted"))
    cmd_outcomes = [o for o in outcomes if o.get("actual_kind") == "run_command"]
    top1 = 0
    for o in cmd_outcomes:
        probs = o.get("probs") or {}
        if probs and max(probs, key=probs.get) == o.get("actual_cmd"):
            top1 += 1
    bins = [[0, 0.0, 0] for _ in range(10)]  # count, sum p, hits
    for o in outcomes:
        for cmd, p in (o.get("probs") or {}).items():
            b = min(int(p * 10), 9)
            bins[b][0] += 1
            bins[b][1] += p
            bins[b][2] += 1 if cmd == o.get("actual_cmd") else 0
    lat = [e.get("latency_s", 0) for e in preds]
    return {
        "predictions": len(preds),
        "predictor": sorted({e.get("predictor") for e in preds if e.get("predictor")}),
        "median_predict_latency_s": sorted(lat)[len(lat) // 2] if lat else None,
        "launches": len(c("launch")),
        "hits": len(hits),
        "misses_on_speculable_commands": len(misses),
        "hit_rate": round(len(hits) / (len(hits) + len(misses)), 3) if (hits or misses) else None,
        "time_saved_s": round(saved, 2),
        "time_wasted_worker_s": round(wasted, 2),
        "command_steps_with_prediction": len(cmd_outcomes),
        "top1_command_accuracy": round(top1 / len(cmd_outcomes), 3) if cmd_outcomes else None,
        "shadow_would_hits": sum(1 for o in outcomes if o.get("would_hit")),
        "predict_errors": len(c("predict_error")),
        "reliability": [
            {"bin": "%.1f-%.1f" % (i / 10, (i + 1) / 10), "n": b[0],
             "mean_p": round(b[1] / b[0], 3) if b[0] else None,
             "hit_rate": round(b[2] / b[0], 3) if b[0] else None}
            for i, b in enumerate(bins) if b[0]
        ],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cwd")
    ap.add_argument("--session")
    ap.add_argument("--since", type=float)
    ap.add_argument("--events", default=events_path())
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    s = summarize(load(a.events, a.cwd, a.session, a.since))
    if a.json:
        print(json.dumps(s, indent=2))
        return
    print("Jevsight stats")
    for k, v in s.items():
        if k != "reliability":
            print("  %-32s %s" % (k, v))
    if s["reliability"]:
        print("  reliability (predicted p vs how often that command actually came next):")
        for r in s["reliability"]:
            print("    p %-9s n=%-4d mean_p=%-6s actual=%s" % (r["bin"], r["n"], r["mean_p"], r["hit_rate"]))


if __name__ == "__main__":
    main()

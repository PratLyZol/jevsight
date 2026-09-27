#!/usr/bin/env python3
"""Estimate what Jevsight would have saved on your past Claude Code sessions.

Reads local session transcripts (~/.claude/projects/<project>/*.jsonl), finds each
shell command Claude ran, and asks the predictor what it would have guessed right
after the previous tool result. A correct guess on a speculable command saves up
to min(command time, Claude's thinking time before it asked).

Caveats printed with the result: command durations come from transcript
timestamps, and a replay cannot know about files changed outside Claude.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from predictor import PredictionError, make_predictor, render_state  # noqa: E402
from safety import classify, normalize  # noqa: E402


def ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def project_dir(project):
    slug = os.path.abspath(project).replace("/", "-").replace(".", "-")
    return os.path.expanduser("~/.claude/projects/" + slug)


def sessions(project, limit):
    files = sorted(glob.glob(os.path.join(project_dir(project), "*.jsonl")), key=os.path.getmtime, reverse=True)
    return files[:limit]


def steps_from(path):
    """Yield (kind, tool, input, t_call, t_result) in order."""
    calls, out, prompt = {}, [], ""
    with open(path) as f:
        for line in f:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            t = ts(rec.get("timestamp") or "")
            msg = rec.get("message") or {}
            content = msg.get("content")
            if rec.get("type") == "user" and isinstance(content, str) and not prompt:
                prompt = content
            if not isinstance(content, list):
                continue
            for c in content:
                if c.get("type") == "tool_use":
                    calls[c.get("id")] = {"tool": c.get("name"), "input": c.get("input") or {}, "t_call": t}
                    out.append(calls[c.get("id")])
                elif c.get("type") == "tool_result" and c.get("tool_use_id") in calls:
                    calls[c["tool_use_id"]]["t_result"] = t
                    calls[c["tool_use_id"]]["error"] = bool(c.get("is_error"))
                elif c.get("type") == "text" and rec.get("type") == "user" and not prompt:
                    prompt = c.get("text") or ""
    return prompt, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=os.getcwd())
    ap.add_argument("--sessions", type=int, default=5)
    ap.add_argument("--alpha", type=float, default=0.25)
    a = ap.parse_args()
    files = sessions(a.project, a.sessions)
    if not files:
        print("No Claude Code transcripts found for %s" % a.project)
        return
    pred = make_predictor()
    total_saved = total_cmds = speculable = hits = 0
    for path in files:
        prompt, calls = steps_from(path)
        steps, history, facts = [], [], {"last_action": "none", "files_edited_since_last_check": "no"}
        prev_result = None
        for c in calls:
            tool, inp = c["tool"], c["input"]
            if tool == "Bash":
                cmd = normalize(inp.get("command") or "")
                total_cmds += 1
                if classify(cmd, a.project) and prev_result and c.get("t_call") and c.get("t_result"):
                    speculable += 1
                    cands = list(dict.fromkeys([h for h in reversed(history) if classify(h, a.project)] + [cmd]))
                    if len(cands) > 1 or history:
                        try:
                            probs = pred.predict(render_state(prompt, steps, facts), cands)["commands"]
                        except PredictionError as e:
                            print("prediction failed: %s" % e)
                            return
                        think = max(0.0, c["t_call"] - prev_result)
                        dur = max(0.0, c["t_result"] - c["t_call"])
                        p = probs.get(cmd, 0.0)
                        ranked = sorted(probs.items(), key=lambda kv: -kv[1])
                        ok = any(k == cmd and v * min(dur, think) - (1 - v) * a.alpha * dur > 0 for k, v in ranked[:2])
                        if ok:
                            hits += 1
                            total_saved += min(dur, think)
                history.append(cmd)
                steps.append("Bash `%s`" % cmd[:120])
                facts["last_action"] = "run_command"
                facts["files_edited_since_last_check"] = "no"
            elif tool in ("Edit", "Write", "MultiEdit"):
                steps.append("%s %s" % (tool, inp.get("file_path", "")))
                facts["last_action"] = "edit_file"
                facts["files_edited_since_last_check"] = "yes"
            else:
                steps.append("%s %s" % (tool, str(inp.get("pattern") or inp.get("file_path") or "")[:100]))
                facts["last_action"] = "read_file"
            prev_result = c.get("t_result") or prev_result
    print("Jevsight backtest (%s predictor) over %d session(s) in %s" % (pred.name, len(files), a.project))
    print("  shell commands run:            %d" % total_cmds)
    print("  speculable (read-only/allowed): %d" % speculable)
    print("  would have been run early:      %d" % hits)
    print("  estimated time saved:           %.1f s" % total_saved)
    print("Caveats: durations come from transcript timestamps; this ignores CPU contention and files changed outside Claude.")


if __name__ == "__main__":
    main()

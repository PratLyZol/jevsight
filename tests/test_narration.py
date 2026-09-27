#!/usr/bin/env python3
"""TranscriptTail: reads Claude's text blocks incrementally, tolerates partial lines, skips sidechains,
and finds the newest transcript in a directory. Plain python3, no network."""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugins", "jevsight", "bin"))
from narration import FeedTail, TranscriptTail, narration_step, n_tool_steps, project_slug, trace_steps  # noqa: E402
from predictor import render_state  # noqa: E402


def entry(kind, blocks, side=False):
    return json.dumps({"type": kind, "isSidechain": side, "message": {"role": kind, "content": blocks}}) + "\n"


def main():
    d = tempfile.mkdtemp()
    old = os.path.join(d, "old.jsonl")
    open(old, "w").write(entry("assistant", [{"type": "text", "text": "stale"}]))
    os.utime(old, (time.time() - 100, time.time() - 100))
    tail = TranscriptTail(search_dir=d, since=time.time() - 5)
    assert tail.poll() == [], "an old transcript must be ignored"
    p = os.path.join(d, "new.jsonl")
    with open(p, "w") as f:
        f.write(entry("user", [{"type": "text", "text": "do the thing"}]))
        f.write(entry("assistant", [{"type": "text", "text": "Two projects.\n  Starting with the first."}]))
        f.write(entry("assistant", [{"type": "tool_use", "name": "mcp__neon__describe_project", "input": {}}]))
        f.write(entry("assistant", [{"type": "text", "text": "subagent chatter"}], side=True))
        half = entry("assistant", [{"type": "text", "text": "Listing its tables."}])
        f.write(half[:20])
    got = tail.poll()
    assert got == [{"text": "Two projects. Starting with the first.", "then_tool": "mcp__neon__describe_project"}], got
    assert tail.poll() == [], "nothing new yet (partial line pending)"
    with open(p, "a") as f:
        f.write(half[20:])
    assert tail.poll() == [{"text": "Listing its tables.", "then_tool": None}]
    assert tail.poll() == []
    # feed written by race.py
    fp = os.path.join(d, "narration.jsonl")
    open(fp, "w").write(json.dumps({"t": 1, "text": " Next,  wedding_inquiries. "}) + "\n" + '{"t": 2, "text": ""}\n')
    feed = FeedTail(fp)
    assert feed.poll() == [{"text": "Next, wedding_inquiries.", "then_tool": None}]
    assert feed.poll() == []
    # trace helpers
    steps = ["a(x) -> short", narration_step("plan"), "b(y) -> short"]
    full = ["a(x) -> long long", narration_step("plan"), "b(y) -> long long"]
    assert n_tool_steps(steps) == 2
    assert trace_steps(steps, full, 1) == ["a(x) -> short", narration_step("plan"), "b(y) -> long long"]
    st = render_state("task", steps, {"k": "v"}, [("TOOLS:", ["- a", "- b"])])
    assert "2 calls" in st and "Claude says:" in st and "- b" in st and "TOOLS:" in st, st
    assert project_slug("/Users/x/jevsight-races/race-1/baseline") == "-Users-x-jevsight-races-race-1-baseline"
    print("ok: narration tail, partial lines, sidechain skip, newest-file discovery, feed, trace helpers")


if __name__ == "__main__":
    main()

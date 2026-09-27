"""Claude's own words between tool calls ("Default branch is main. Listing its tables.").

Two sources, same interface (`poll()` returns [{"text", "then_tool"}]):

- `FeedTail`: a JSONL file of {"text": ...} lines written by whoever drives Claude Code through
  `--output-format stream-json` (race/race.py does). The stream emits each text block as its own
  event 0.3-0.5s before the tool call it precedes, so the words reach Jev before the call.
- `TranscriptTail`: the Claude Code session transcript. Claude Code stamps the text block 0.3-0.6s
  before the tool_use block but writes both to the file together when the call is emitted, so from
  this source the words arrive with the call, not before it. `then_tool` names the tool call that
  followed the text in the same write, so callers can put the words back in front of that call.
"""
from __future__ import annotations

import json
import os
import re
import time

NARRATION_PREFIX = "Claude says: "
MAX_TEXT = 400


def project_slug(cwd: str) -> str:
    """Claude Code's transcript folder name for a working directory."""
    return re.sub(r"[^A-Za-z0-9]", "-", cwd)


def transcript_dir(config_dir: str | None, cwd: str) -> str:
    return os.path.join(config_dir or os.path.expanduser("~/.claude"), "projects", project_slug(cwd))


def newest_transcript(dir_path: str, since: float = 0.0):
    best = None
    try:
        names = os.listdir(dir_path)
    except OSError:
        return None
    for n in names:
        if not n.endswith(".jsonl"):
            continue
        p = os.path.join(dir_path, n)
        try:
            m = os.path.getmtime(p)
        except OSError:
            continue
        if m >= since and (best is None or m > best[0]):
            best = (m, p)
    return best[1] if best else None


def clean_text(text: str) -> str:
    return " ".join(str(text).split())[:MAX_TEXT]


def narration_step(text: str) -> str:
    return NARRATION_PREFIX + json.dumps(clean_text(text))


def is_narration(step: str) -> bool:
    return step.startswith(NARRATION_PREFIX)


def n_tool_steps(steps) -> int:
    return sum(1 for s in steps if not is_narration(s))


def trace_steps(steps, full, recent: int = 3):
    """The trace shown to Jev: short lines, except the newest few results, which are shown in full."""
    if len(full) != len(steps):
        return list(steps)
    return list(steps[:-recent]) + list(full[-recent:])


class TranscriptTail:
    """Yields new assistant text blocks from a transcript, from where the last poll stopped."""

    def __init__(self, path=None, search_dir=None, since=0.0, start_at_end=False):
        self.path, self.search_dir, self.since = path, search_dir, since
        self.offset, self.buf = 0, b""
        if path and start_at_end:
            try:
                self.offset = os.path.getsize(path)
            except OSError:
                pass

    def poll(self):
        if not self.path and self.search_dir:
            self.path = newest_transcript(self.search_dir, self.since)
        if not self.path:
            return []
        try:
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                chunk = f.read()
        except OSError:
            return []
        if not chunk:
            return []
        self.offset += len(chunk)
        lines = (self.buf + chunk).split(b"\n")
        self.buf = lines.pop()  # a line still being written
        out, open_items = [], []
        for line in lines:
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("type") != "assistant" or e.get("isSidechain"):
                continue
            for b in (e.get("message") or {}).get("content") or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text":
                    t = clean_text(b.get("text") or "")
                    if t:
                        item = {"text": t, "then_tool": None}
                        out.append(item)
                        open_items.append(item)
                elif b.get("type") == "tool_use":
                    for item in open_items:
                        item["then_tool"] = b.get("name")
                    open_items = []
        return out


class FeedTail:
    """Tails a JSONL feed of {"text": ...} lines (see race/race.py). Words arrive before the call."""

    def __init__(self, path):
        self.path, self.offset, self.buf = path, 0, b""

    def poll(self):
        try:
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                chunk = f.read()
        except OSError:
            return []
        if not chunk:
            return []
        self.offset += len(chunk)
        lines = (self.buf + chunk).split(b"\n")
        self.buf = lines.pop()
        out = []
        for line in lines:
            try:
                t = clean_text(json.loads(line).get("text") or "")
            except (ValueError, AttributeError):
                continue
            if t:
                out.append({"text": t, "then_tool": None})
        return out


def session_tail(transcript_path=None):
    """For the daemon: the feed if the harness provides one, else the session's transcript."""
    feed = os.environ.get("JEVSIGHT_NARRATION_FEED")
    if feed:
        return FeedTail(feed)
    return TranscriptTail(transcript_path, start_at_end=True) if transcript_path else None


def default_tail(start_ts=None) -> TranscriptTail:
    """For the MCP proxy: JEVSIGHT_TRANSCRIPT, else the newest transcript in JEVSIGHT_TRANSCRIPT_DIR,
    else the newest one Claude Code keeps for this working directory."""
    feed = os.environ.get("JEVSIGHT_NARRATION_FEED")
    if feed:
        return FeedTail(feed)
    path = os.environ.get("JEVSIGHT_TRANSCRIPT")
    if path:
        return TranscriptTail(path)
    d = os.environ.get("JEVSIGHT_TRANSCRIPT_DIR") or transcript_dir(os.environ.get("CLAUDE_CONFIG_DIR"), os.getcwd())
    return TranscriptTail(search_dir=d, since=(start_ts or time.time()) - 5.0)

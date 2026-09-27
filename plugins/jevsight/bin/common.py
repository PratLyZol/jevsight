"""Shared helpers for the Jevsight hook client, daemon and tools."""
from __future__ import annotations

import json
import os
import tempfile
import time

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN_DIR = os.path.join(PLUGIN_ROOT, "bin")


def data_dir() -> str:
    d = os.environ.get("JEVSIGHT_DATA") or os.environ.get("CLAUDE_PLUGIN_DATA") or os.path.expanduser("~/.jevsight")
    os.makedirs(d, exist_ok=True)
    return d


def sock_path() -> str:
    p = os.path.join(data_dir(), "jevsight.sock")
    if len(p) > 100:  # macOS limits unix socket paths to 104 bytes
        p = os.path.join(tempfile.gettempdir(), "jevsight-%d.sock" % os.getuid())
    return p


def opt(name: str, default=None):
    """Read a setting from plugin userConfig env vars or JEVSIGHT_* env vars."""
    for key in ("CLAUDE_PLUGIN_OPTION_" + name.upper(), "CLAUDE_PLUGIN_OPTION_" + name, "JEVSIGHT_" + name.upper()):
        v = os.environ.get(key)
        if v not in (None, ""):
            return v
    return default


KEY_ENV = {"openrouter": "OPENROUTER_API_KEY", "vercel": "AI_GATEWAY_API_KEY", "typesafe": "TYPESAFE_API_KEY"}


def provider() -> str:
    """Explicit provider setting wins; otherwise pick whichever provider has a key set."""
    p = (opt("provider") or "").strip().lower()
    if p in KEY_ENV:
        return p
    for name in ("vercel", "openrouter", "typesafe"):
        if (os.environ.get(KEY_ENV[name]) or "").strip():
            return name
    return "vercel"


def api_key():
    """True-ish if any Jev key is configured (each route picks its own provider's key)."""
    return (opt("api_key") or "").strip() or next(
        ((os.environ.get(k) or "").strip() for k in KEY_ENV.values() if (os.environ.get(k) or "").strip()), None)


def mode() -> str:
    m = (opt("mode", "shadow") or "shadow").strip().lower()
    return m if m in ("shadow", "on", "off") else "shadow"


def events_path() -> str:
    return os.path.join(data_dir(), "events.jsonl")


def log_event(kind: str, **fields) -> None:
    rec = {"ts": round(time.time(), 3), "type": kind}
    rec.update(fields)
    try:
        with open(events_path(), "a") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass

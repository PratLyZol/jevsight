#!/usr/bin/env python3
"""Route a project's stdio MCP servers through the Jevsight proxy.

  python3 plugins/jevsight/bin/wrap_mcp.py <project>/.mcp.json          # wrap
  python3 plugins/jevsight/bin/wrap_mcp.py <project>/.mcp.json --undo   # restore from .bak

Each stdio server entry ("command": ...) becomes
  "command": "python3", "args": ["<this dir>/mcp_proxy.py", "--", <original command>, <original args...>]
with JEVSIGHT_MODE=on added to its env. Remote servers ("type": "http"/"sse", or a "url") are never
touched. A .bak copy of the file is written first; --undo restores it.
"""
from __future__ import annotations

import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROXY = os.path.join(HERE, "mcp_proxy.py")


def is_remote(server):
    return bool(server.get("url")) or str(server.get("type", "")).lower() in ("http", "sse", "streamable-http")


def is_wrapped(server):
    args = server.get("args") or []
    return len(args) >= 2 and args[0].endswith("mcp_proxy.py") and args[1] == "--"


def wrap(path):
    cfg = json.load(open(path))
    servers = cfg.get("mcpServers") or {}
    changed = []
    for name, s in servers.items():
        if is_remote(s) or is_wrapped(s) or not s.get("command"):
            continue
        original = [s["command"]] + list(s.get("args") or [])
        s["command"] = sys.executable if os.path.basename(sys.executable).startswith("python") else "python3"
        s["args"] = [PROXY, "--"] + original
        env = dict(s.get("env") or {})
        env.setdefault("JEVSIGHT_MODE", "on")
        s["env"] = env
        changed.append(name)
    if not changed:
        print("nothing to wrap in %s (no unwrapped stdio servers)" % path)
        return
    shutil.copyfile(path, path + ".bak")
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    print("wrapped %s in %s (backup: %s.bak)" % (", ".join(changed), path, path))


def undo(path):
    bak = path + ".bak"
    if not os.path.exists(bak):
        sys.exit("no backup at %s" % bak)
    shutil.copyfile(bak, path)
    os.remove(bak)
    print("restored %s from %s" % (path, bak))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)
    path = os.path.abspath(args[0])
    if "--undo" in sys.argv:
        undo(path)
    else:
        wrap(path)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Real Neon smoke test through the Jevsight proxy (read-only; needs NEON_API_KEY in .env).

  python3 tests/neon_smoke.py

Sends initialize, tools/list and list_projects through the proxy to the real Neon MCP server and
prints: the tool names, whether arguments are wrapped under `params`, which tools carry a
readOnlyHint, and whether the project ids match the proxy's id filter. It never prints the key,
connection strings, or full results. Jev is not involved (mode=off).
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "plugins", "jevsight", "bin"))
from mcp_client import Client  # noqa: E402
import mcp_proxy as mp  # noqa: E402

PKG = "@neondatabase/mcp-server-neon@0.6.5"


def load_dotenv():
    path = os.path.join(ROOT, ".env")
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if v.strip():
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main():
    load_dotenv()
    key = os.environ.get("NEON_API_KEY", "").strip()
    if not key:
        sys.exit("NEON_API_KEY is not set. Add it to .env (edit the file yourself).")
    tmp = tempfile.mkdtemp(prefix="jevsight-smoke-")
    env = dict(os.environ)
    env.update(JEVSIGHT_MODE="off", JEVSIGHT_DATA=tmp, JEVSIGHT_PREDICTOR="heuristic")
    cmd = [sys.executable, os.path.join(ROOT, "plugins", "jevsight", "bin", "mcp_proxy.py"), "--",
           "npx", "-y", PKG, "start", key, "--no-analytics"]
    print("starting %s through the proxy (first run downloads the package) ..." % PKG)
    c = Client(cmd, env)
    try:
        c.send("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "smoke", "version": "0"}})
        m = c.read(timeout=120)
        assert m and "result" in m, "initialize failed: %r" % (m,)
        print("server: %s" % json.dumps(m["result"].get("serverInfo")))
        c.send("notifications/initialized", notify=True)
        rid = c.send("tools/list")
        m = c.read(timeout=60)
        assert m and m.get("id") == rid, "tools/list failed"
        tools = m["result"]["tools"]
        print("%d tools:" % len(tools))
        wrapped, hinted = [], []
        for t in tools:
            props, req, wrap = mp.tool_props(t)
            if wrap:
                wrapped.append(t["name"])
            if (t.get("annotations") or {}).get("readOnlyHint"):
                hinted.append(t["name"])
            print("  %-28s %-5s required=%s optional=%s" % (
                t["name"], "safe" if mp.is_safe(t["name"], mp.READ_ONLY) else "-", req,
                sorted(k for k in props if k not in req)))
        print("arguments wrapped under `params`: %d of %d" % (len(wrapped), len(tools)))
        print("readOnlyHint published by: %s" % (hinted or "none"))
        missing = sorted(n for n in mp.READ_ONLY if n not in {t["name"] for t in tools})
        if missing:
            print("WARNING: READ_ONLY names not offered by this server: %s" % missing)
        lp = next(t for t in tools if t["name"] == "list_projects")
        args = {"params": {}} if mp.tool_props(lp)[2] else {}
        msg, lat = c.call("list_projects", args, timeout=60)
        text = mp.response_text(msg)
        ids = re.findall(r'"id"\s*:\s*"([^"]+)"', text)
        pf = mp.VALUE_FILTERS["projectId"]
        print("list_projects: %.1fs, %d ids in the result" % (lat, len(ids)))
        for i in ids[:8]:
            print("  %-32s %s" % (i, "matches projectId filter" if pf.search(i) else "(not a project id by the filter)"))
        ok = [i for i in ids if pf.search(i)]
        if not ok:
            print("WARNING: no id matched VALUE_FILTERS['projectId']; update the regex in mcp_proxy.py")
        values = {}
        mp.extract_values(values, text)
        print("keys seen in the result: %s" % sorted(values)[:20])
        print("candidates the proxy would build next: %d" % len(mp.build_candidates(
            {t["name"]: t for t in tools}, mp.READ_ONLY, values, {})))
        print("OK")
    finally:
        c.close()


if __name__ == "__main__":
    main()

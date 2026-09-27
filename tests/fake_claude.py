#!/usr/bin/env python3
"""A stand-in for the `claude` CLI so race.py can be rehearsed with no network and no login.

race.py runs it exactly like Claude Code:
  fake_claude.py -p <prompt> --output-format stream-json --verbose --mcp-config <file> ...
It reads the first stdio server from the MCP config (command, args, env), talks MCP to it, walks a
fixed read-only chain with a "thinking" pause between calls, and prints Claude Code stream-json
events (assistant tool_use, user tool_result, final result) on stdout.

Env: FAKE_THINK  seconds to pause between calls (default 1.5)
"""
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from mcp_client import Client  # noqa: E402

THINK = float(os.environ.get("FAKE_THINK", "1.5"))


def arg(flag, default=None):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def text_of(result):
    return "\n".join(c.get("text", "") for c in (result or {}).get("content") or [] if c.get("type") == "text")


def main():
    prompt = arg("-p", "")
    cfg_path = arg("--mcp-config")
    if not cfg_path:
        sys.exit("fake_claude: --mcp-config required")
    cfg = json.load(open(cfg_path))
    sname, server = next(iter(cfg["mcpServers"].items()))
    env = dict(os.environ)
    env.update(server.get("env") or {})
    t0 = time.time()
    emit({"type": "system", "subtype": "init", "model": "fake", "tools": ["mcp__%s__*" % sname], "mcp_servers": [sname]})
    c = Client([server["command"]] + list(server.get("args") or []), env, cwd=os.getcwd())
    names = c.handshake("fake-claude")
    wrapped = True  # Neon and the fake wrap arguments under params
    steps = [("list_projects", {}), ]
    n = 0
    tables, project, branch = [], None, None

    def call(tool, args):
        nonlocal n
        n += 1
        tid = "toolu_%03d" % n
        emit({"type": "assistant", "parent_tool_use_id": None,
              "message": {"role": "assistant", "content": [{"type": "tool_use", "id": tid, "name": "mcp__%s__%s" % (sname, tool),
                                                             "input": {"params": args} if wrapped else args}]}})
        msg, _ = c.call(tool, {"params": args} if wrapped else args, timeout=60)
        res = msg.get("result") or {}
        txt = text_of(res) if "result" in msg else json.dumps(msg.get("error"))
        emit({"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid,
                                                                       "content": [{"type": "text", "text": txt}],
                                                                       "is_error": "error" in msg or bool(res.get("isError"))}]}})
        time.sleep(THINK)
        return txt

    try:
        import re
        txt = call("list_projects", {})
        try:
            project = json.loads(txt)["projects"][0]["id"]
        except (ValueError, KeyError, IndexError, TypeError):
            m = re.search(r'"id":\s*"((?!org-)[a-z]+-[a-z]+-[a-z0-9]+)"', txt)
            project = m.group(1) if m else None
        txt = call("describe_project", {"projectId": project})
        m = re.search(r'"default_branch_id":\s*"(br-[^"]+)"', txt) or re.search(r'"id":\s*"(br-[^"]+)"', txt)
        branch = m.group(1) if m else None
        txt = call("get_database_tables", {"projectId": project, "branchId": branch})
        tables = re.findall(r'"table_name":\s*"([^"]+)"', txt)
        cols = {}
        for t in tables[:3]:
            cols[t] = call("describe_table_schema", {"tableName": t, "projectId": project, "branchId": branch})
    finally:
        c.close()
    report = ["# Schema report for %s" % project, "", "Branch: %s" % branch, ""]
    for t in tables[:3]:
        report.append("## %s" % t)
        report.append("```")
        report.append(cols.get(t, "")[:400])
        report.append("```")
    dur = time.time() - t0
    emit({"type": "result", "subtype": "success", "is_error": False, "duration_ms": int(dur * 1000),
          "duration_api_ms": int(THINK * n * 1000), "num_turns": n + 1, "result": "\n".join(report),
          "total_cost_usd": 0.0, "session_id": "fake"})


if __name__ == "__main__":
    main()

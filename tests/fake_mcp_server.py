#!/usr/bin/env python3
"""A Neon-shaped stdio MCP server for tests. No network, no keys.

Newline-delimited JSON-RPC on stdin/stdout. Same tool names and argument shapes as
@neondatabase/mcp-server-neon 0.6.5: every tool takes its arguments under `params`
(set FAKE_WRAP=0 for flat arguments). One write tool, `create_branch`, changes the
state so that stale results are detectable: after it, `get_database_tables` lists an
extra `audit` table.

Env:
  FAKE_DELAY  seconds every tools/call sleeps (default 1.0)
  FAKE_STATS  path of a JSON file with per-call counts and every request id seen
  FAKE_WRAP   1 (default) wraps arguments under `params`, 0 uses flat arguments
"""
from __future__ import annotations

import copy
import json
import os
import sys
import threading
import time

DELAY = float(os.environ.get("FAKE_DELAY", "1.0"))
STATS = os.environ.get("FAKE_STATS")
WRAP = os.environ.get("FAKE_WRAP", "1") != "0"

PROJECT = "proud-sun-123456"
PROJECT2 = "quiet-lake-654321"
BRANCH = "br-cool-9"
ORG = "org-fake-demo-1"

S = {"type": "string"}


def opt(desc=""):
    return {"type": "string", "description": desc}


# name -> (properties, required)
TOOL_DEFS = [
    ("list_projects", {"cursor": opt("cursor"), "limit": {"type": "number", "default": 10}, "search": opt(), "org_id": opt()}, []),
    ("list_organizations", {"search": opt()}, []),
    ("describe_project", {"projectId": opt("The ID of the project to describe")}, ["projectId"]),
    ("describe_branch", {"projectId": S, "branchId": S, "databaseName": opt()}, ["projectId", "branchId"]),
    ("get_database_tables", {"projectId": S, "branchId": opt("optional; default branch if absent"), "databaseName": opt()}, ["projectId"]),
    ("describe_table_schema", {"tableName": S, "projectId": S, "branchId": opt("optional; default branch if absent"), "databaseName": opt()},
     ["tableName", "projectId"]),
    ("list_branch_computes", {"projectId": opt(), "branchId": opt()}, []),
    ("create_branch", {"projectId": S, "branchName": opt()}, ["projectId"]),
    ("run_sql", {"sql": S, "projectId": S, "branchId": opt(), "databaseName": opt()}, ["sql", "projectId"]),
]


def tool_list():
    out = []
    for name, props, req in TOOL_DEFS:
        inner = {"type": "object", "properties": props, "required": req, "additionalProperties": False}
        schema = {"type": "object", "properties": {"params": inner}, "required": ["params"]} if WRAP else inner
        out.append({"name": name, "description": "fake %s" % name, "inputSchema": schema})
    return out


def initial_state():
    return {"branches": [{"id": BRANCH, "name": "main", "default": True, "project_id": PROJECT}], "extra_tables": []}


COLUMNS = {
    "users": [("id", "integer"), ("email", "text"), ("created_at", "timestamp")],
    "orders": [("id", "integer"), ("user_id", "integer"), ("total_cents", "integer")],
    "items": [("id", "integer"), ("order_id", "integer"), ("sku", "text")],
    "audit": [("id", "integer"), ("note", "text")],
}


def text(obj):
    return {"content": [{"type": "text", "text": json.dumps(obj, indent=2)}]}


def result_for(name, args, state):
    """Deterministic result for a call given the server state. Tests import this to compute
    what a direct call would return."""
    a = args.get("params", args) if isinstance(args, dict) else {}
    a = a if isinstance(a, dict) else {}
    if name == "list_projects":
        projects = [{"id": PROJECT, "name": "demo", "org_id": ORG, "region_id": "aws-us-east-2"},
                    {"id": PROJECT2, "name": "scratch", "org_id": ORG, "region_id": "aws-us-east-2"}]
        return text({"organization": {"name": "Personal", "id": ORG}, "projects": projects})
    if name == "list_organizations":
        return text([{"id": ORG, "name": "Personal"}])
    if name == "describe_project":
        pid = a.get("projectId")
        if pid not in (PROJECT, PROJECT2):
            return {"content": [{"type": "text", "text": "project not found: %s" % pid}], "isError": True}
        branches = state["branches"] if pid == PROJECT else [{"id": "br-plain-1", "name": "main", "default": True, "project_id": pid}]
        return {"content": [{"type": "text", "text": "This project is called %s." % ("demo" if pid == PROJECT else "scratch")},
                            {"type": "text", "text": "It contains the following branches: " + json.dumps(
                                {"branches": branches, "default_branch_id": branches[0]["id"]}, indent=2)}]}
    if name == "describe_branch":
        return text({"branch": {"id": a.get("branchId"), "project_id": a.get("projectId")}, "databases": [{"name": "neondb"}]})
    if name == "get_database_tables":
        names = ["users", "orders", "items"] + list(state["extra_tables"])
        return text([{"table_schema": "public", "table_name": n, "table_type": "BASE TABLE"} for n in names])
    if name == "describe_table_schema":
        t = a.get("tableName")
        cols = COLUMNS.get(t)
        if cols is None or (t == "audit" and "audit" not in state["extra_tables"]):
            return {"content": [{"type": "text", "text": "no such table: %s" % t}], "isError": True}
        return text({"raw": [{"column_name": c, "data_type": d} for c, d in cols],
                     "formatted": "\n".join("%s %s" % (c, d) for c, d in cols)})
    if name == "list_branch_computes":
        return text([{"id": "ep-fake-compute-1", "branch_id": BRANCH, "type": "read_write"}])
    if name == "create_branch":
        n = len(state["branches"])
        b = {"id": "br-new-%d" % n, "name": a.get("branchName") or "branch-%d" % n, "default": False, "project_id": a.get("projectId")}
        return text({"branch": b})
    if name == "run_sql":
        return text([{"count": 3}])
    return {"content": [{"type": "text", "text": "unknown tool %s" % name}], "isError": True}


def apply_write(name, args, state):
    if name == "create_branch":
        n = len(state["branches"])
        state["branches"].append({"id": "br-new-%d" % n, "name": "branch-%d" % n, "default": False, "project_id": PROJECT})
        if "audit" not in state["extra_tables"]:
            state["extra_tables"].append("audit")


class Server:
    def __init__(self):
        self.state = initial_state()
        self.lock = threading.Lock()
        self.stats = {"calls": {}, "ids": [], "by_name": {}}

    def record(self, name, args, rid):
        if not STATS:
            return
        key = "%s %s" % (name, json.dumps(args, sort_keys=True, separators=(",", ":")))
        self.stats["calls"][key] = self.stats["calls"].get(key, 0) + 1
        self.stats["by_name"][name] = self.stats["by_name"].get(name, 0) + 1
        self.stats["ids"].append(str(rid))
        tmp = STATS + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.stats, f)
        os.replace(tmp, STATS)

    def reply(self, msg):
        with self.lock:
            sys.stdout.write(json.dumps(msg) + "\n")
            sys.stdout.flush()

    def handle(self, msg):
        method, rid = msg.get("method"), msg.get("id")
        if method is None:
            return  # a response to something we never asked; ignore
        if rid is None:
            return  # notification
        if method == "initialize":
            self.reply({"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}}, "serverInfo": {"name": "fake-neon", "version": "0.0.1"}}})
        elif method == "ping":
            self.reply({"jsonrpc": "2.0", "id": rid, "result": {}})
        elif method == "tools/list":
            self.reply({"jsonrpc": "2.0", "id": rid, "result": {"tools": tool_list()}})
        elif method == "tools/call":
            p = msg.get("params") or {}
            name, args = p.get("name"), p.get("arguments") or {}
            with self.lock:
                self.record(name, args, rid)
                snapshot = copy.deepcopy(self.state)
                if name == "create_branch":
                    apply_write(name, args, self.state)
            time.sleep(DELAY)
            if name not in {t[0] for t in TOOL_DEFS}:
                self.reply({"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": "unknown tool %s" % name}})
                return
            self.reply({"jsonrpc": "2.0", "id": rid, "result": result_for(name, args, snapshot)})
        else:
            self.reply({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "method not found: %s" % method}})

    def serve(self):
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            threading.Thread(target=self.handle, args=(msg,), daemon=True).start()


if __name__ == "__main__":
    Server().serve()

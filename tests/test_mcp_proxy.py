#!/usr/bin/env python3
"""End-to-end test of the Jevsight MCP proxy against the fake Neon server. No network, no Jev.

  python3 tests/test_mcp_proxy.py            # ~40s
  python3 tests/test_mcp_proxy.py --quick    # skips the flat-arguments and passthrough runs

Plain python3, no pytest. Exits non-zero on the first failing assertion.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROXY = os.path.join(ROOT, "plugins", "jevsight", "bin", "mcp_proxy.py")
FAKE = os.path.join(HERE, "fake_mcp_server.py")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "plugins", "jevsight", "bin"))
import fake_mcp_server as fake  # noqa: E402

FAKE_DELAY = 1.0
PROJECT, BRANCH = fake.PROJECT, fake.BRANCH


class Client:
    """Minimal newline-delimited JSON-RPC client over a subprocess."""

    def __init__(self, cmd, env, log_path=None):
        self.proc = subprocess.Popen(cmd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        self.next_id = 1
        self.sent = set()
        self.seen_ids = []
        self.log = open(log_path, "w") if log_path else None

    def send(self, method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        rid = None
        if not notify:
            rid = self.next_id
            self.next_id += 1
            msg["id"] = rid
            self.sent.add(rid)
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        return rid

    def read(self, timeout=10.0):
        """Next message from the proxy, or None after `timeout` seconds."""
        import select
        end = time.time() + timeout
        while True:
            left = end - time.time()
            if left <= 0:
                return None
            r, _, _ = select.select([self.proc.stdout], [], [], left)
            if not r:
                return None
            line = self.proc.stdout.readline()
            if not line:
                return None
            if self.log:
                self.log.write(line)
            try:
                msg = json.loads(line)
            except ValueError:
                raise AssertionError("non-JSON on proxy stdout: %r" % line[:200])
            self.seen_ids.append(msg.get("id"))
            return msg

    def call(self, name, args, timeout=10.0):
        rid = self.send("tools/call", {"name": name, "arguments": args})
        t0 = time.time()
        msg = self.read(timeout)
        assert msg is not None, "no reply to %s" % name
        assert msg.get("id") == rid, "reply id %r for request %r (%s)" % (msg.get("id"), rid, name)
        return msg, time.time() - t0

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()
        if self.log:
            self.log.close()


def events(path):
    out = []
    if os.path.exists(path):
        for line in open(path):
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def wait_for_event(path, kind, timeout=3.0, **match):
    end = time.time() + timeout
    while time.time() < end:
        for e in events(path):
            if e.get("type") == kind and all(e.get(k) == v for k, v in match.items()):
                return e
        time.sleep(0.1)
    return None


def wrap(args, wrapped):
    return {"params": args} if wrapped else args


def make_env(tmp, wrapped, jev_mode="on"):
    env = dict(os.environ)
    for k in list(env):
        if k.startswith("JEVSIGHT_") or k.startswith("CLAUDE_PLUGIN_OPTION_") or k.endswith("_API_KEY"):
            env.pop(k)
    env.update(JEVSIGHT_PREDICTOR="heuristic", JEVSIGHT_MODE=jev_mode, JEVSIGHT_DATA=tmp,
               JEVSIGHT_TASK="test: walk one Neon project's schema",
               FAKE_DELAY=str(FAKE_DELAY), FAKE_STATS=os.path.join(tmp, "fake_stats.json"), FAKE_WRAP="1" if wrapped else "0")
    return env


def handshake(c):
    m = c.read()
    return m


def scenario_speculation(wrapped):
    tag = "wrapped" if wrapped else "flat"
    tmp = tempfile.mkdtemp(prefix="jevsight-test-%s-" % tag)
    env = make_env(tmp, wrapped)
    ev_path = os.path.join(tmp, "events.jsonl")
    c = Client([sys.executable, PROXY, "--", sys.executable, FAKE], env, os.path.join(tmp, "client.log"))
    state = fake.initial_state()
    try:
        rid = c.send("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}})
        m = c.read()
        assert m and m.get("id") == rid and "result" in m, "initialize failed: %r" % m
        c.send("notifications/initialized", notify=True)
        rid = c.send("tools/list")
        m = c.read()
        assert m and m.get("id") == rid, "tools/list failed"
        names = {t["name"] for t in m["result"]["tools"]}
        assert "create_branch" in names and "describe_table_schema" in names, names

        def check(name, args, expect_hit=None):
            msg, lat = c.call(name, args)
            exp = fake.result_for(name, args, state)
            assert msg.get("result") == exp, "%s: result differs from a direct call\n got: %s\n exp: %s" % (
                name, json.dumps(msg.get("result"))[:300], json.dumps(exp)[:300])
            return lat

        # 1. list_projects with limit=10 (a schema default: must canonicalize away)
        lat = check("list_projects", wrap({"limit": 10}, wrapped))
        assert lat >= FAKE_DELAY * 0.8, "first call cannot be a hit (%.2fs)" % lat
        time.sleep(2.0)
        # 2. describe_project
        lat = check("describe_project", wrap({"projectId": PROJECT}, wrapped))
        time.sleep(2.0)
        # 3. get_database_tables with the default branch spelled out
        lat = check("get_database_tables", wrap({"projectId": PROJECT, "branchId": BRANCH}, wrapped))
        time.sleep(2.0)
        # 4. describe_table_schema(users): the stand-in ranks this first, so it should be a HIT
        lat_users = check("describe_table_schema", wrap({"tableName": "users", "projectId": PROJECT, "branchId": BRANCH}, wrapped))
        hit = wait_for_event(ev_path, "hit", timeout=1.0)
        assert hit is not None, "expected at least one hit by now; events: %s" % [e["type"] for e in events(ev_path)]
        assert lat_users < FAKE_DELAY / 2, "hit should be served fast, took %.2fs (fake delay %.1fs)" % (lat_users, FAKE_DELAY)
        time.sleep(2.0)
        # 5. describe_table_schema(orders) WITHOUT branchId: equals the launched call with the default branch (alias)
        lat_orders = check("describe_table_schema", wrap({"tableName": "orders", "projectId": PROJECT}, wrapped))
        hits = [e for e in events(ev_path) if e["type"] == "hit"]
        assert len(hits) >= 2, "expected an alias hit on orders; hits: %s" % hits
        assert any(e.get("alias") for e in hits), "the orders hit should be an alias match: %s" % hits
        assert lat_orders < FAKE_DELAY / 2, "alias hit should be fast, took %.2fs" % lat_orders
        time.sleep(2.0)   # a guess for the next table is now running or done
        # 6. create_branch: a write. Everything saved must be thrown away.
        launched_before = [e for e in events(ev_path) if e["type"] == "launch"]
        msg, _ = c.call("create_branch", wrap({"projectId": PROJECT, "branchName": "feature"}, wrapped))
        assert "result" in msg, msg
        fake.apply_write("create_branch", {}, state)
        wasted = wait_for_event(ev_path, "wasted", timeout=1.0, reason="stale:write:create_branch")
        assert wasted is not None, "expected a wasted event after the write; events: %s" % [
            (e["type"], e.get("reason")) for e in events(ev_path)]
        time.sleep(2.0)
        # 7. one more read: must reflect the write (the fake now lists an `audit` table)
        n_launch = len([e for e in events(ev_path) if e["type"] == "launch"])
        msg, lat = c.call("get_database_tables", wrap({"projectId": PROJECT}, wrapped))
        exp = fake.result_for("get_database_tables", {}, state)
        assert msg.get("result") == exp, "stale result served after a write:\n got %s" % json.dumps(msg.get("result"))[:300]
        assert "audit" in json.dumps(msg.get("result")), "post-write read should list the audit table"
        # 8. cancellation of a request served from a job that is still running: no reply may arrive
        end = time.time() + 3.0
        launch = None
        while time.time() < end and launch is None:
            ls = [e for e in events(ev_path) if e["type"] == "launch"]
            if len(ls) > n_launch:
                launch = ls[-1]
            time.sleep(0.02)
        assert launch is not None, "no new guess after the last read"
        lname, largs = launch["cmd"].split(" ", 1)
        largs = json.loads(largs)
        rid = c.send("tools/call", {"name": lname, "arguments": largs})
        c.send("notifications/cancelled", {"requestId": rid, "reason": "test"}, notify=True)
        m = c.read(timeout=FAKE_DELAY + 1.0)
        assert m is None or m.get("id") != rid, "reply arrived for a cancelled request served from a job: %r" % m
        cancelled = wait_for_event(ev_path, "cancelled", timeout=1.0)
        assert cancelled is not None, "expected a cancelled event"
        # the job is still usable afterwards
        msg, lat = c.call(lname, largs)
        assert "result" in msg, msg

        # --- global assertions
        stats = json.load(open(os.path.join(tmp, "fake_stats.json")))
        assert stats["by_name"].get("create_branch") == 1, "create_branch reached upstream %s times" % stats["by_name"].get("create_branch")
        assert not any(n in stats["by_name"] for n in ("run_sql",)), "a NEVER tool was speculated: %s" % stats["by_name"]
        assert any(i.startswith("jevsight-") for i in stats["ids"]), "no speculative call ever reached upstream"
        assert not any(isinstance(i, str) and i.startswith("jevsight-") for i in c.seen_ids), "a jevsight-* id leaked to the client"
        assert all(i in c.sent for i in c.seen_ids if i is not None), "reply with an unknown id: %s" % [i for i in c.seen_ids if i not in c.sent]
        ev = events(ev_path)
        kinds = {e["type"] for e in ev}
        assert {"predict", "launch", "hit", "saved", "job_done", "wasted", "miss", "outcome"} <= kinds, kinds
        assert all(e.get("predictor") == "heuristic" for e in ev if e["type"] == "predict"), "predictor must be the stand-in here"
        print("  %s: ok  hits=%d launches=%d wasted=%d  hit latency %.3fs / alias %.3fs" % (
            tag, len([e for e in ev if e["type"] == "hit"]), len([e for e in ev if e["type"] == "launch"]),
            len([e for e in ev if e["type"] == "wasted"]), lat_users, lat_orders))
    finally:
        c.close()
        shutil.rmtree(tmp, ignore_errors=True)


def scenario_passthrough():
    tmp = tempfile.mkdtemp(prefix="jevsight-test-off-")
    env = make_env(tmp, True, jev_mode="off")
    c = Client([sys.executable, PROXY, "--", sys.executable, FAKE], env)
    state = fake.initial_state()
    try:
        rid = c.send("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})
        assert c.read().get("id") == rid
        c.send("notifications/initialized", notify=True)
        rid = c.send("tools/list")
        assert c.read().get("id") == rid
        for name, args in (("list_projects", {}), ("describe_project", {"projectId": PROJECT}),
                           ("get_database_tables", {"projectId": PROJECT})):
            msg, lat = c.call(name, {"params": args})
            assert msg.get("result") == fake.result_for(name, {"params": args}, state)
            assert lat >= FAKE_DELAY * 0.8, "mode=off must not serve early (%.2fs)" % lat
            time.sleep(1.5)
        stats = json.load(open(os.path.join(tmp, "fake_stats.json")))
        assert not any(i.startswith("jevsight-") for i in stats["ids"]), "mode=off launched a speculative call"
        assert sum(stats["by_name"].values()) == 3, stats["by_name"]
        ev = events(os.path.join(tmp, "events.jsonl"))
        assert not any(e["type"] in ("launch", "hit") for e in ev), [e["type"] for e in ev]
        print("  passthrough (mode=off): ok")
    finally:
        c.close()
        shutil.rmtree(tmp, ignore_errors=True)


def scenario_upstream_dies():
    """Upstream exits mid-request: the client must get a JSON-RPC error, not silence."""
    tmp = tempfile.mkdtemp(prefix="jevsight-test-die-")
    env = make_env(tmp, True)
    env["FAKE_DELAY"] = "3"
    c = Client([sys.executable, PROXY, "--", sys.executable, FAKE], env)
    try:
        rid = c.send("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})
        assert c.read().get("id") == rid
        rid = c.send("tools/call", {"name": "list_projects", "arguments": {"params": {}}})
        time.sleep(0.5)
        # find and kill the fake server (child of the proxy)
        out = subprocess.run(["pgrep", "-P", str(c.proc.pid)], capture_output=True, text=True).stdout.split()
        assert out, "no upstream child found"
        for pid in out:
            os.kill(int(pid), 9)
        m = c.read(timeout=5)
        assert m is not None and m.get("id") == rid and "error" in m, "expected an error reply, got %r" % m
        print("  upstream exit: ok (%s)" % m["error"]["message"])
    finally:
        c.close()
        shutil.rmtree(tmp, ignore_errors=True)


def unit_tests():
    import mcp_proxy as mp
    tools = {t["name"]: t for t in fake.tool_list()}
    lp = tools["list_projects"]
    assert mp.call_key("list_projects", {"params": {"limit": 10}}, lp) == mp.call_key("list_projects", {"params": {}}, lp)
    assert mp.call_key("list_projects", {"params": {"limit": 20}}, lp) != mp.call_key("list_projects", {"params": {}}, lp)
    assert mp.call_key("list_projects", {"params": {"limit": True}}, lp) != mp.call_key("list_projects", {"params": {"limit": 1}}, lp)
    dts = tools["describe_table_schema"]
    dflt = {PROJECT: BRANCH}
    a = mp.alias_args(dts, {"params": {"tableName": "users", "projectId": PROJECT}}, dflt)
    assert a == {"params": {"tableName": "users", "projectId": PROJECT, "branchId": BRANCH}}, a
    a = mp.alias_args(dts, {"params": {"tableName": "users", "projectId": PROJECT, "branchId": BRANCH}}, dflt)
    assert a == {"params": {"tableName": "users", "projectId": PROJECT}}, a
    assert mp.alias_args(dts, {"params": {"tableName": "users", "projectId": PROJECT, "branchId": "br-other"}}, dflt) is None
    assert mp.alias_args(tools["describe_branch"], {"params": {"projectId": PROJECT}}, dflt) is None, "branchId is required there"
    assert mp.alias_args(dts, {"params": {"tableName": "users", "projectId": "unknown"}}, dflt) is None
    assert mp.is_safe("describe_project", mp.READ_ONLY) and not mp.is_safe("create_branch", mp.READ_ONLY)
    assert not mp.is_safe("run_sql", mp.READ_ONLY | {"run_sql"}), "NEVER must beat a read-only hint"
    values, used = {}, {}
    mp.extract_values(values, fake.result_for("list_projects", {}, fake.initial_state())["content"][0]["text"])
    assert values["id"].index(PROJECT) < values["id"].index(fake.PROJECT2), values["id"]  # listing order kept
    cands = mp.build_candidates(tools, mp.READ_ONLY, values, used)
    keys = [k for k, _, _ in cands]
    assert keys[0].startswith("describe_project ") and PROJECT in keys[0], keys[:3]
    assert not any("br-" in k for k in keys), "no branch ids known yet"
    assert not any(k.startswith("create_branch") or k.startswith("run_sql") for k in keys)
    # alias in the wrong direction never matches a different branch
    print("  unit: ok (%d candidates after list_projects)" % len(cands))


def main():
    quick = "--quick" in sys.argv
    print("jevsight mcp proxy tests")
    unit_tests()
    scenario_speculation(wrapped=True)
    if not quick:
        scenario_speculation(wrapped=False)
        scenario_passthrough()
    scenario_upstream_dies()
    print("ALL PASSED")


if __name__ == "__main__":
    main()

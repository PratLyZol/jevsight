"""Minimal newline-delimited JSON-RPC client over a subprocess, for tests and rehearsals."""
from __future__ import annotations

import json
import select
import subprocess
import time


class Client:
    def __init__(self, cmd, env, log_path=None, cwd=None):
        self.proc = subprocess.Popen(cmd, env=env, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     text=True, bufsize=1)
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
        """Next message from the server, or None after `timeout` seconds."""
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
                raise AssertionError("non-JSON on server stdout: %r" % line[:200])
            self.seen_ids.append(msg.get("id"))
            return msg

    def call(self, name, args, timeout=10.0):
        rid = self.send("tools/call", {"name": name, "arguments": args})
        t0 = time.time()
        msg = self.read(timeout)
        assert msg is not None, "no reply to %s" % name
        assert msg.get("id") == rid, "reply id %r for request %r (%s)" % (msg.get("id"), rid, name)
        return msg, time.time() - t0

    def handshake(self, name="client"):
        rid = self.send("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                       "clientInfo": {"name": name, "version": "0"}})
        m = self.read()
        assert m and m.get("id") == rid and "result" in m, "initialize failed: %r" % m
        self.send("notifications/initialized", notify=True)
        rid = self.send("tools/list")
        m = self.read()
        assert m and m.get("id") == rid and "result" in m, "tools/list failed: %r" % m
        return [t["name"] for t in m["result"]["tools"]]

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()
        if self.log:
            self.log.close()

#!/usr/bin/env python3
"""Thin hook client: forwards the hook event to the Jevsight daemon.

It never blocks Claude for long and never fails a tool call: on any problem it
prints nothing and exits 0, so Claude Code carries on exactly as without Jevsight.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from common import data_dir, mode, sock_path  # noqa: E402


def connect(path, timeout):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect(path)
    return s


def ensure_daemon():
    path = sock_path()
    try:
        return connect(path, 2.0)
    except OSError:
        pass
    log = open(os.path.join(data_dir(), "daemon.log"), "ab")
    subprocess.Popen([sys.executable, os.path.join(HERE, "daemon.py")], stdin=subprocess.DEVNULL,
                     stdout=log, stderr=log, start_new_session=True, env=os.environ.copy())
    deadline = time.time() + 3.0
    while time.time() < deadline:
        try:
            return connect(path, 2.0)
        except OSError:
            time.sleep(0.03)
    return None


def main():
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode() == "off":
        return 0
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        return 0
    try:
        s = ensure_daemon()
        if s is None:
            return 0
        s.sendall((json.dumps({"event": event, "payload": payload}) + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        s.close()
        reply = json.loads(buf.decode() or "{}")
    except (OSError, ValueError):
        return 0
    out = reply.get("hook_output")
    if out:
        sys.stdout.write(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Race plain Claude Code against Claude Code + Jevsight on the same task.

Coding apps (small, next, fix): both sides get a fresh copy of the starter, the same prompt and
the same model, and start at the same instant. The clock stops when Claude finishes; then the
script runs `npm run check` on each copy to confirm the app really works.

MCP app (neon): both sides explore the same Neon account, read-only, through the Neon MCP server.
The jevsight side talks to it through the Jevsight MCP proxy, which runs Jev's predicted next call
early. The clock stops when Claude hands in its markdown report.

Usage:
  python3 race/race.py                    # one race, live split screen
  python3 race/race.py --app neon         # Neon MCP race (needs NEON_API_KEY in .env)
  python3 race/race.py --app github       # GitHub MCP race, read-only on a public repo (needs `gh auth login`)
  python3 race/race.py --app fetch        # web-fetch MCP race: walks the Python asyncio docs (needs uvx, no key)
  python3 race/race.py --repeat 5         # five races, results appended to race/results/races.jsonl
  python3 race/race.py --jevsight-mode shadow   # measure overhead (predict only)
  python3 race/race.py --only jevsight    # run one side (handy for recording traces)

Needs: claude (Claude Code) on PATH, node/npm, and a Jev key in .env or the environment
(AI_GATEWAY_API_KEY, OPENROUTER_API_KEY or TYPESAFE_API_KEY). Without a key the Jevsight side uses the
stand-in heuristic predictor and says so on screen.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEON_PKG = "@neondatabase/mcp-server-neon@0.6.5"
NEON_PROMPT = (
    "Using only the Neon MCP tools, explore my Neon account and write a markdown report on ONE project's schema. "
    "Work step by step, one tool call at a time, deciding each next call from the previous result: list the projects, "
    "pick the first project that has tables, describe that project to find its default branch, list the tables on "
    "that branch, then describe each table's schema one table at a time. The report must have one section per table "
    "with its columns and types, and a final section naming which tables reference each other. "
    "This is strictly read-only: do not create, modify or delete anything, do not run SQL, and do not fetch connection strings."
)
GITHUB_BIN = os.path.expanduser("~/.jevsight/bin/github-mcp-server")
GITHUB_RELEASE = "v1.12.2"
GITHUB_REPO = "modelcontextprotocol/servers"
GITHUB_PROMPT = (
    "Using only the GitHub MCP tools, investigate the public repository %s and write a markdown report on its three most "
    "recently merged pull requests. Work step by step, one tool call at a time, choosing each call from the previous result: "
    "list the merged pull requests, then for each of the three newest read the pull request, read its list of changed files, "
    "read its review comments, and look at the merge commit it produced. The report needs one section per pull request "
    "(what changed, which files, what reviewers said, who merged it) and a closing paragraph on what the maintainers seem to "
    "be focused on right now. This is strictly read-only: do not create, edit, comment on, star or fork anything." % GITHUB_REPO
)
FETCH_PAGES = ["asyncio.html", "asyncio-runner.html", "asyncio-task.html", "asyncio-stream.html", "asyncio-sync.html",
               "asyncio-subprocess.html", "asyncio-queue.html"]
FETCH_PROMPT = (
    "Using only the fetch tool, write a markdown cheat sheet of Python's asyncio high-level API from these pages, read in "
    "this order, one fetch at a time: " + ", ".join("https://docs.python.org/3/library/" + p for p in FETCH_PAGES) + ". "
    "When a page comes back truncated, fetch the rest of it (with the start_index the tool suggests) before moving to the "
    "next page. The cheat sheet needs one section per page with the main functions and classes, each with a one-line "
    "description, and a closing section on which primitives to reach for first. Read only; do not fetch anything else."
)
APPS = {
    "small": {"kind": "npm", "starter": os.path.join(ROOT, "race", "starter"),
              "prompt": "Implement SPEC.md. You're done when `npm test` and `npm run typecheck` both pass."},
    "next": {"kind": "npm", "starter": os.path.join(ROOT, "race", "starter-next"),
             "prompt": "Implement SPEC.md. You're done when `npm run check` passes."},
    "fix": {"kind": "npm", "starter": os.path.join(ROOT, "race", "broken-next"),
            "prompt": "`npm run check` is failing on this expense tracker. Fix the code until it passes. "
                      "Do not edit files under test/ or the config files."},
    "neon": {"kind": "mcp", "starter": None, "server": "neon", "prompt": NEON_PROMPT,
             "verify_rx": re.compile(r'"table_name"\s*:\s*"([^"]+)"'), "verify_what": "tables"},
    "github": {"kind": "mcp", "starter": None, "server": "github", "prompt": GITHUB_PROMPT,
               "verify_rx": re.compile(r'"number"\s*:\s*(\d+)'), "verify_what": "issue/PR numbers"},
    # mcp-server-fetch publishes no readOnlyHint, so its one tool is allowlisted for the proxy explicitly
    "fetch": {"kind": "mcp", "starter": None, "server": "fetch", "prompt": FETCH_PROMPT, "read_only": "fetch",
              "verify_rx": re.compile(r'"url"\s*:\s*"[^"]*/([^/"]+?)(?:\.html)?"(?=[,}])'), "verify_from": "args", "verify_what": "pages"},
}
# Same for both sides: keeps the user's personal Claude Code setup from steering the race.
RACE_SYSTEM_NOTE = "You are working alone in a benchmark run. Work directly in this session and do not spawn subagents."
CLEAN_CONFIG = os.path.expanduser("~/.jevsight-claude")
PLUGIN = os.path.join(ROOT, "plugins", "jevsight")
PROXY = os.path.join(PLUGIN, "bin", "mcp_proxy.py")
sys.path.insert(0, os.path.join(PLUGIN, "bin"))
from narration import transcript_dir  # noqa: E402
RESULTS = os.path.join(ROOT, "race", "results")
JEV_KEYS = ("AI_GATEWAY_API_KEY", "OPENROUTER_API_KEY", "TYPESAFE_API_KEY", "JEVSIGHT_API_KEY")

ALLOWED_TOOLS = [
    "Read", "Edit", "Write", "MultiEdit", "Glob", "Grep", "LS", "TodoWrite",
    "Bash(npm:*)", "Bash(npx:*)", "Bash(node:*)", "Bash(ls:*)", "Bash(cat:*)", "Bash(grep:*)",
    "Bash(rg:*)", "Bash(git:*)", "Bash(find:*)", "Bash(head:*)", "Bash(tail:*)", "Bash(wc:*)",
    "Bash(mkdir:*)", "Bash(cd:*)", "Bash(pwd)",
]
MCP_DISALLOWED = "Bash Edit Write MultiEdit NotebookEdit Agent Task WebFetch WebSearch"
# Only these go in the project's settings file, because Jevsight reads it to decide
# which non-read-only commands are safe to run early. Keep it to checks.
SPECULATION_ALLOW = [
    "Bash(npm test)", "Bash(npm test:*)", "Bash(npm run typecheck)", "Bash(npm run check)",
    "Bash(npm run lint)", "Bash(npm run build)", "Bash(npx vitest run:*)", "Bash(npx tsc --noEmit:*)",
    "Bash(npx eslint:*)", "Bash(npx next build)",
]

C = {"reset": "\033[0m", "dim": "\033[2m", "bold": "\033[1m", "green": "\033[32m", "yellow": "\033[33m",
     "cyan": "\033[36m", "magenta": "\033[35m", "red": "\033[31m"}


def load_dotenv():
    path = os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                if v:
                    os.environ.setdefault(k.strip(), v)


def fmt(t):
    return "%02d:%04.1f" % (int(t // 60), t % 60)


def write_private(path, obj):
    """Write JSON that may hold secrets: owner-only, never printed."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f, indent=2)


class Side:
    def __init__(self, name, workdir, env, args, prompt, app, claude_cmd="claude", mcp_config=None, feed=None):
        self.name, self.workdir, self.env, self.args, self.prompt = name, workdir, env, args, prompt
        self.app, self.claude_cmd, self.mcp_config = app, claude_cmd, mcp_config
        self.feed = open(feed, "a") if feed else None   # Claude's narration, forwarded to Jevsight as it streams
        self.kind = app["kind"]
        self.bash_wait = 0.0
        self.mcp_wait = 0.0
        self.waits = []
        self.lines = []
        self.start = None
        self.end = None
        self.result = None
        self.tool_calls = 0
        self.bash_calls = 0
        self.mcp_calls = 0
        self.check = None
        self.tables_seen = []
        self.tables_named = []
        self.proc = None
        self.pending = {}
        self.rc = None

    def elapsed(self):
        if self.start is None:
            return 0.0
        return (self.end or time.time()) - self.start

    def wait_total(self):
        return self.mcp_wait if self.kind == "mcp" else self.bash_wait

    def calls(self):
        return self.mcp_calls if self.kind == "mcp" else self.bash_calls

    def add(self, text):
        self.lines.append("%s %s" % (fmt(self.elapsed()), text))

    def command(self):
        cmd = [self.claude_cmd, "-p", self.prompt, "--output-format", "stream-json", "--verbose",
               "--append-system-prompt", RACE_SYSTEM_NOTE]
        if self.kind == "npm":
            cmd += ["--permission-mode", "acceptEdits", "--allowedTools", " ".join(ALLOWED_TOOLS),
                    "--disallowedTools", "Agent Task"]
        else:
            cmd += ["--allowedTools", "mcp__%s" % self.app["server"], "--disallowedTools", MCP_DISALLOWED,
                    "--mcp-config", self.mcp_config, "--strict-mcp-config"]
        return cmd + self.args

    def run(self, t0):
        self.start = t0
        cmd = self.command()
        run_dir = os.path.dirname(self.workdir)
        times = open(os.path.join(run_dir, "%s.times.jsonl" % self.name), "w")
        with open(os.path.join(run_dir, "%s.stream.jsonl" % self.name), "w") as log:
            try:
                self.proc = subprocess.Popen(cmd, cwd=self.workdir, env=self.env, stdout=subprocess.PIPE,
                                             stderr=subprocess.STDOUT, text=True, bufsize=1)
            except OSError as e:
                self.add(C["red"] + "cannot start %s: %s" % (cmd[0], e) + C["reset"])
                self.end = time.time()
                times.close()
                return
            for n, raw in enumerate(self.proc.stdout):
                log.write(raw)
                log.flush()
                times.write(json.dumps({"line": n, "t": round(time.time() - self.start, 3)}) + "\n")
                times.flush()
                try:
                    ev = json.loads(raw)
                except ValueError:
                    if raw.strip():
                        self.add(C["red"] + raw.strip()[:120] + C["reset"])
                    continue
                self.on_event(ev)
            self.proc.wait()
            self.rc = self.proc.returncode
        times.close()
        self.end = self.end or time.time()

    def on_event(self, ev):
        t = ev.get("type")
        if t == "assistant":
            for c in (ev.get("message") or {}).get("content") or []:
                if c.get("type") == "text" and self.feed and ev.get("parent_tool_use_id") is None:
                    # the stream emits each text block as its own event, before the tool call it precedes
                    self.feed.write(json.dumps({"t": round(time.time(), 3), "text": c.get("text") or ""}) + "\n")
                    self.feed.flush()
                if c.get("type") == "tool_use":
                    self.tool_calls += 1
                    name, inp = c.get("name") or "", c.get("input") or {}
                    if name == "Bash":
                        self.bash_calls += 1
                        cmd = " ".join(inp.get("command", "").split())
                        self.pending[c.get("id")] = (cmd, time.time(), len(self.lines), name)
                        self.add(C["cyan"] + "$ " + cmd[:80] + C["reset"] + C["dim"] + "  ...running" + C["reset"])
                    elif name.startswith("mcp__"):
                        self.mcp_calls += 1
                        short = name.split("__", 2)[-1]
                        key = "%s %s" % (short, json.dumps(inp, sort_keys=True, separators=(",", ":")))
                        if self.app.get("verify_from") == "args":
                            for tn in self.app["verify_rx"].findall(key):
                                if tn not in self.tables_seen:
                                    self.tables_seen.append(tn)
                        self.pending[c.get("id")] = (key, time.time(), len(self.lines), name)
                        self.add(C["cyan"] + "mcp " + key[:76] + C["reset"] + C["dim"] + "  ...running" + C["reset"])
                    elif name in ("Edit", "Write", "MultiEdit"):
                        self.add(C["yellow"] + "%s %s" % (name, os.path.relpath(inp.get("file_path", ""), self.workdir)) + C["reset"])
                    else:
                        what = inp.get("file_path") or inp.get("pattern") or inp.get("path") or ""
                        if isinstance(what, str) and what.startswith(self.workdir):
                            what = os.path.relpath(what, self.workdir)
                        self.add(C["dim"] + "%s %s" % (name, what) + C["reset"])
        elif t == "user":
            now = time.time()
            for c in (ev.get("message") or {}).get("content") or []:
                if c.get("type") == "tool_result" and c.get("tool_use_id") in self.pending:
                    cmd, t_call, idx, name = self.pending.pop(c.get("tool_use_id"))
                    wait = now - t_call
                    if name == "Bash":
                        self.bash_wait += wait
                    else:
                        self.mcp_wait += wait
                        body = c.get("content")
                        if isinstance(body, list):
                            body = " ".join(x.get("text", "") for x in body if isinstance(x, dict))
                        if self.app.get("verify_from") != "args":
                            for tn in self.app["verify_rx"].findall(str(body or "")):
                                if tn not in self.tables_seen:
                                    self.tables_seen.append(tn)
                    fast = wait < 1.0 and self.name == "jevsight"
                    self.waits.append({"cmd": cmd, "wait_s": round(wait, 2)})
                    tag = (C["green"] + C["bold"] + "  %.1fs" % wait) if fast else (C["yellow"] + "  waited %.1fs" % wait)
                    if idx < len(self.lines):
                        self.lines[idx] = self.lines[idx].replace(C["dim"] + "  ...running" + C["reset"], tag + C["reset"])
        elif t == "result":
            self.end = time.time()
            self.result = ev
            self.add(C["bold"] + "Claude finished (%s turns)" % ev.get("num_turns", "?") + C["reset"])
            if self.feed:
                self.feed.close()
                self.feed = None

    def verify(self):
        if self.kind == "npm":
            r = subprocess.run(["npm", "run", "check"], cwd=self.workdir, capture_output=True, text=True)
            self.check = r.returncode == 0
            tail = (r.stdout + r.stderr).strip().splitlines()[-3:]
            self.add((C["green"] + "npm run check: PASS" if self.check else C["red"] + "npm run check: FAIL") + C["reset"])
            for line in tail:
                self.add(C["dim"] + line[:100] + C["reset"])
            return
        # MCP: the deliverable is the answer. Save it, and check it names tables the run actually saw.
        answer = (self.result or {}).get("result") or ""
        if not isinstance(answer, str):
            answer = json.dumps(answer)
        with open(os.path.join(os.path.dirname(self.workdir), "%s.answer.md" % self.name), "w") as f:
            f.write(answer)
        low = answer.lower()

        def named(t):   # the slug itself, or (for page slugs like asyncio-sync) its last word as a stem: sync -> synchronization
            t = t.lower()
            if re.search(r"(?<![\w.])%s(?![\w.])" % re.escape(t), low):
                return True
            stem = t.rsplit("-", 1)[-1] if self.app.get("verify_from") == "args" and "-" in t else None
            return bool(stem and re.search(r"(?<![\w.])%s" % re.escape(stem), low))
        self.tables_named = [t for t in self.tables_seen if named(t)]
        ok = self.result is not None and not self.result.get("is_error") and bool(self.tables_named)
        self.check = ok
        what = self.app["verify_what"]
        self.add((C["green"] + "answer: names %d of %d %s seen" % (len(self.tables_named), len(self.tables_seen), what)
                  if ok else C["red"] + "answer: FAIL (finished=%s, %s seen=%d, named=%d)" % (
                      self.result is not None, what, len(self.tables_seen), len(self.tables_named))) + C["reset"])


def tail_feed(path, feed, stats, stop):
    pos = 0
    while not stop.is_set():
        try:
            with open(path) as f:
                f.seek(pos)
                for line in f:
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    t = e.get("type")
                    if t == "daemon_start":
                        feed.append(C["magenta"] + "jevsight up: predictor=%s mode=%s" % (e.get("predictor"), e.get("mode")) + C["reset"])
                    elif t == "predict":
                        stats["predict"] += 1
                    elif t == "launch":
                        feed.append(C["magenta"] + "guess  p=%.2f  ev=%+.1fs  running early: %s" % (e.get("p", 0), e.get("ev", 0), e.get("cmd")) + C["reset"])
                    elif t == "hit":
                        feed.append(C["green"] + C["bold"] + "HIT    %s  (started %.1fs before Claude asked)" % (e.get("cmd"), e.get("head_start_s", 0)) + C["reset"])
                    elif t == "saved":
                        feed.append(C["green"] + "saved  %.1fs on %s" % (e.get("saved_s", 0), e.get("cmd")) + C["reset"])
                    elif t == "wasted":
                        feed.append(C["dim"] + "wasted %.1fs (%s): %s" % (e.get("wasted_s", 0), e.get("reason", ""), e.get("cmd")) + C["reset"])
                    elif t == "predict_error":
                        stats["errors"] += 1
                        feed.append(C["red"] + "predict error: %s" % e.get("error", "")[:90] + C["reset"])
                pos = f.tell()
        except OSError:
            pass
        time.sleep(0.2)


def visible_len(s):
    out, i = 0, 0
    while i < len(s):
        if s[i] == "\033":
            while i < len(s) and s[i] != "m":
                i += 1
        else:
            out += 1
        i += 1
    return out


def clip(s, width):
    res, vis, i = "", 0, 0
    while i < len(s) and vis < width:
        if s[i] == "\033":
            j = s.index("m", i) + 1
            res += s[i:j]
            i = j
            continue
        res += s[i]
        vis += 1
        i += 1
    return res + C["reset"] + " " * max(0, width - vis)


def render(sides, feed, title, stats):
    cols, rows = shutil.get_terminal_size((160, 45))
    half = (cols - 3) // 2
    body = max(5, rows - 14)
    jev = "  |  Jev calls: %d ok, %d failed" % (stats["predict"], stats["errors"]) if (stats["predict"] or stats["errors"]) else ""
    out = ["\033[H\033[2J", C["bold"] + title + jev + C["reset"]]
    heads = []
    for s in sides:
        state = "done" if s.end else "running"
        what = "MCP calls" if s.kind == "mcp" else "commands"
        heads.append(clip(C["bold"] + "%s  %s  [%s]  waiting on %s: %.1fs" % (s.name.upper(), fmt(s.elapsed()), state, what, s.wait_total()) + C["reset"], half))
    out.append(" | ".join(heads))
    out.append("-" * cols)
    cols_lines = [s.lines[-body:] for s in sides]
    for i in range(body):
        row = []
        for cl in cols_lines:
            row.append(clip(cl[i] if i < len(cl) else "", half))
        out.append(" | ".join(row))
    out.append("-" * cols)
    out.append(C["bold"] + "Jevsight feed" + C["reset"])
    for line in feed[-8:]:
        out.append(clip(line, cols))
    sys.stdout.write("\n".join(out) + "\n")
    sys.stdout.flush()


def prepare(run_dir, name, app):
    wd = os.path.join(run_dir, name)
    if app["kind"] == "mcp":
        os.makedirs(wd)   # nothing to copy: the task lives in the database
        return wd
    shutil.copytree(app["starter"], wd, ignore=shutil.ignore_patterns("node_modules", ".next"))
    os.makedirs(os.path.join(wd, ".claude"), exist_ok=True)
    with open(os.path.join(wd, ".claude", "settings.json"), "w") as f:
        json.dump({"permissions": {"allow": SPECULATION_ALLOW}}, f, indent=2)
    subprocess.run(["git", "init", "-q"], cwd=wd)
    subprocess.run(["git", "add", "-A"], cwd=wd)
    subprocess.run(["git", "-c", "user.email=race@jevsight", "-c", "user.name=race", "commit", "-qm", "starter"], cwd=wd)
    print("installing dependencies for %s ..." % name)
    subprocess.run(["npm", "install", "--no-audit", "--no-fund", "--silent"], cwd=wd, check=True)
    return wd


def github_token():
    tok = os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN", "").strip()
    if not tok and shutil.which("gh"):
        tok = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True).stdout.strip()
    if not tok:
        sys.exit("No GitHub token: set GITHUB_PERSONAL_ACCESS_TOKEN or run `gh auth login`.")
    return tok


def server_cmd(app, a):
    """(command list, env) for the upstream MCP server. Secrets go where the server insists on
    them: Neon only takes its key as a positional argument (no env var in 0.6.5); GitHub takes an env var."""
    if a.server_cmd:
        return shlex.split(a.server_cmd), {}
    if app["server"] == "neon":
        key = os.environ.get("NEON_API_KEY", "").strip()
        if not key:
            sys.exit("NEON_API_KEY is not set. Add it to .env (edit the file yourself; never paste keys into chat).")
        return ["npx", "-y", NEON_PKG, "start", key, "--no-analytics"], {}
    if app["server"] == "github":
        if not os.path.isfile(GITHUB_BIN):
            print("downloading github-mcp-server %s to %s ..." % (GITHUB_RELEASE, os.path.dirname(GITHUB_BIN)))
            os.makedirs(os.path.dirname(GITHUB_BIN), exist_ok=True)
            arch = "arm64" if os.uname().machine == "arm64" else "x86_64"
            tgz = os.path.join(os.path.dirname(GITHUB_BIN), "gh-mcp.tar.gz")
            subprocess.run(["gh", "release", "download", GITHUB_RELEASE, "--repo", "github/github-mcp-server",
                            "--pattern", "github-mcp-server_Darwin_%s.tar.gz" % arch, "--output", tgz, "--clobber"], check=True)
            subprocess.run(["tar", "xzf", tgz, "-C", os.path.dirname(GITHUB_BIN), "github-mcp-server"], check=True)
            os.remove(tgz)
        # --read-only: the server itself refuses to expose any writing tool, on top of our own list
        return [GITHUB_BIN, "stdio", "--read-only"], {"GITHUB_PERSONAL_ACCESS_TOKEN": github_token()}
    if app["server"] == "fetch":
        if not shutil.which("uvx"):
            sys.exit("uvx is not on PATH (install uv); the fetch race runs `uvx mcp-server-fetch`.")
        return [shutil.which("uvx"), "mcp-server-fetch"], {}
    sys.exit("no server command for app %s" % app["server"])


def mcp_config_for(side, a, run_dir, data, prompt, app):
    """Per-side MCP config. Baseline talks to the server directly; jevsight goes through the proxy."""
    upstream, senv = server_cmd(app, a)
    env = dict(senv)
    if side == "baseline":
        server = {"command": upstream[0], "args": upstream[1:]}
    else:
        env.update({"JEVSIGHT_MODE": a.jevsight_mode, "JEVSIGHT_DATA": data, "JEVSIGHT_TASK": prompt,
                    "JEVSIGHT_NARRATION_FEED": os.path.join(data, "narration.jsonl")})
        # fallback source for Claude's narration: where Claude Code writes this side's transcript
        env["JEVSIGHT_TRANSCRIPT_DIR"] = transcript_dir(a.claude_config, os.path.join(run_dir, side))
        if app.get("read_only"):
            env["JEVSIGHT_READ_ONLY"] = app["read_only"]
        for k in JEV_KEYS + ("JEVSIGHT_PROVIDER", "JEVSIGHT_PREDICTOR", "JEVSIGHT_ALPHA", "JEVSIGHT_TIMEOUT", "JEVSIGHT_COOLDOWN"):
            if os.environ.get(k):
                env[k] = os.environ[k]
        server = {"command": sys.executable, "args": [PROXY, "--"] + upstream}
    if env:
        server["env"] = env
    path = os.path.join(run_dir, "%s.mcp.json" % side)
    write_private(path, {"mcpServers": {app["server"]: server}})
    return path


def warm(app, a):
    """Fetch the server once before the race so neither side pays for it."""
    if a.server_cmd:
        return
    if app["server"] == "neon":
        print("warming npx cache for %s ..." % NEON_PKG)
        subprocess.run(["npx", "-y", NEON_PKG, "export-tools"], capture_output=True, text=True)   # needs no key
    elif app["server"] == "github":
        server_cmd(app, a)   # downloads the binary if missing
    elif app["server"] == "fetch":
        # first use of mcp-server-fetch runs an npm install that prints to stdout (a protocol violation
        # that would break the first side's session), so do one real fetch here, off the clock
        print("warming mcp-server-fetch with one page ...")
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                                                              "clientInfo": {"name": "race", "version": "0"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "fetch", "arguments": {"url": "https://docs.python.org/3/library/asyncio.html", "max_length": 500}}}]
        try:
            subprocess.run(["uvx", "mcp-server-fetch"], input="".join(json.dumps(m) + "\n" for m in msgs),
                           capture_output=True, text=True, timeout=180)
        except (OSError, subprocess.TimeoutExpired) as e:
            print("  (warm-up failed: %s)" % e)


def scoreboard(rec):
    sd = rec["sides"]
    mcp = rec["kind"] == "mcp"
    what = "waiting on MCP calls" if mcp else "waiting on commands"
    ok = "answer ok" if mcp else "app works"
    line = C["bold"] + "=" * 72 + C["reset"]
    print("\n" + line)
    print(C["bold"] + "  RESULTS" + C["reset"])
    print("  %-10s %12s %22s %10s" % ("", "total time", what, ok))
    for n in ("baseline", "jevsight"):
        if n in sd:
            v = sd[n]
            print("  %-10s %11.1fs %21.1fs %10s" % (n, v["seconds"], v["wait_s"], "yes" if v["check_passed"] else "NO"))
    if "baseline" in sd and "jevsight" in sd:
        b, j = sd["baseline"], sd["jevsight"]
        bw = b["wait_s"] / max(1, b["calls"])
        jw = j["wait_s"] / max(1, j["calls"])
        unit = "MCP call" if mcp else "shell command"
        print(C["green"] + C["bold"] + "\n  avg wait per %s:  baseline %.1fs  vs  jevsight %.1fs" % (unit, bw, jw) + C["reset"])
        if b["seconds"] > 0:
            d = b["seconds"] - j["seconds"]
            print(C["bold"] + "  jevsight finished %.1fs %s (%.0f%%)" % (abs(d), "faster" if d > 0 else "slower", 100 * abs(d) / b["seconds"]) + C["reset"])
        if mcp:
            print("  %s named in the answers: baseline %s, jevsight %s -> %s" % (
                rec.get("verify_what", "ids"), sorted(b.get("answer_tables") or []), sorted(j.get("answer_tables") or []),
                "same set" if rec.get("same_tables") else "DIFFERENT"))
        print(C["dim"] + "  One race is noisy: Claude takes a different path each run. Use --repeat 5 for medians." + C["reset"])
    print(line)


def race_once(a, index):
    app = APPS[a.app]
    prompt = a.prompt or app["prompt"]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = os.path.join(a.runs_dir, "race-%s-%d" % (stamp, index))
    os.makedirs(run_dir)
    data = os.path.join(run_dir, "jevsight-data")
    with open(os.path.join(run_dir, "prompt.txt"), "w") as f:
        f.write(prompt)
    names = ["baseline", "jevsight"] if not a.only else [a.only]
    sides, secret_files = [], []
    if app["kind"] == "mcp":
        warm(app, a)
    try:
        for name in names:
            wd = prepare(run_dir, name, app)
            env = dict(os.environ)
            if a.claude_config:
                env["CLAUDE_CONFIG_DIR"] = a.claude_config  # clean Claude Code config: no personal hooks/plugins/MCP/CLAUDE.md
            extra = []
            if a.model:
                extra += ["--model", a.model]
            mcp_config = feed = None
            if name == "jevsight":
                os.makedirs(data, exist_ok=True)
                feed = os.path.join(data, "narration.jsonl")
                env.update(JEVSIGHT_MODE=a.jevsight_mode, JEVSIGHT_DATA=data, JEVSIGHT_NARRATION_FEED=feed)
                if app["kind"] == "npm":
                    extra += ["--plugin-dir", PLUGIN]
            else:
                env.update(JEVSIGHT_MODE="off")
            if app["kind"] == "mcp":
                mcp_config = mcp_config_for(name, a, run_dir, data, prompt, app)
                secret_files.append(mcp_config)
            env.setdefault("NEXT_TELEMETRY_DISABLED", "1")
            sides.append(Side(name, wd, env, extra, prompt, app, a.claude_cmd, mcp_config, feed))
        feed, stats = [], {"predict": 0, "errors": 0}
        has_key = any(os.environ.get(k) for k in JEV_KEYS) and (os.environ.get("JEVSIGHT_PREDICTOR", "").lower() != "heuristic")
        title = "Jevsight race #%d  |  app: %s  |  same prompt, same model  |  predictor: %s" % (
            index, a.app, "Jev" if has_key else "HEURISTIC STAND-IN (no Jev key set)")
        stop = threading.Event()
        threading.Thread(target=tail_feed, args=(os.path.join(data, "events.jsonl"), feed, stats, stop), daemon=True).start()
        t0 = time.time()
        threads = [threading.Thread(target=s.run, args=(t0,), daemon=True) for s in sides]
        for t in threads:
            t.start()
        while any(t.is_alive() for t in threads):
            if not a.no_ui:
                render(sides, feed, title, stats)
            time.sleep(0.25)
        for s in sides:
            s.verify()
        if not a.no_ui:
            render(sides, feed, title, stats)
        stop.set()
    finally:
        for p in secret_files:   # these hold API keys
            try:
                os.remove(p)
            except OSError:
                pass
    rec = {"ts": time.time(), "app": a.app, "kind": app["kind"], "verify_what": app.get("verify_what"), "run_dir": run_dir, "model": a.model,
           "jevsight_mode": a.jevsight_mode, "predictor": "jev" if has_key else "heuristic",
           "jev_calls": stats["predict"], "jev_errors": stats["errors"], "sides": {}}
    for s in sides:
        rec["sides"][s.name] = {"seconds": round(s.elapsed(), 2), "check_passed": s.check, "exit_code": s.rc,
                                "tool_calls": s.tool_calls, "bash_calls": s.bash_calls, "mcp_calls": s.mcp_calls,
                                "calls": s.calls(), "wait_s": round(s.wait_total(), 2),
                                "wait_on_commands_s": round(s.bash_wait, 2), "wait_on_mcp_s": round(s.mcp_wait, 2),
                                "waits": s.waits, "answer_tables": s.tables_named, "tables_seen": s.tables_seen,
                                "cost_usd": (s.result or {}).get("total_cost_usd"),
                                "turns": (s.result or {}).get("num_turns")}
    if len(sides) == 2 and app["kind"] == "mcp":
        rec["same_tables"] = set(sides[0].tables_named) == set(sides[1].tables_named)
    if os.path.exists(os.path.join(data, "events.jsonl")):
        sys.path.insert(0, os.path.join(PLUGIN, "bin"))
        from stats import load, summarize
        rec["jevsight_stats"] = summarize(load(os.path.join(data, "events.jsonl")))
    results = os.path.join(a.runs_dir, "races.jsonl") if a.rehearsal else os.path.join(RESULTS, "races.jsonl")
    os.makedirs(os.path.dirname(results), exist_ok=True)
    with open(results, "a") as f:
        f.write(json.dumps(rec) + "\n")
    scoreboard(rec)
    for n, v in rec["sides"].items():
        print("%-9s %7.1fs  check=%s  tool calls=%d  %s=%d" % (
            n, v["seconds"], "PASS" if v["check_passed"] else "FAIL", v["tool_calls"],
            "mcp" if app["kind"] == "mcp" else "bash", v["calls"]))
    st = rec.get("jevsight_stats")
    if st:
        print("jevsight: hits=%s misses=%s saved=%.1fs wasted=%.1fs top1=%s predict_errors=%s" % (
            st["hits"], st["misses_on_speculable_commands"], st["time_saved_s"], st["time_wasted_worker_s"],
            st["top1_command_accuracy"], st["predict_errors"]))
    print("run dir: %s" % run_dir)
    return rec


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--app", choices=sorted(APPS), default=None)
    ap.add_argument("--prompt", help="override the app's prompt (same for both sides)")
    ap.add_argument("--model", default=os.environ.get("RACE_MODEL"))
    ap.add_argument("--jevsight-mode", default="on", choices=["on", "shadow"])
    ap.add_argument("--only", choices=["baseline", "jevsight"])
    ap.add_argument("--runs-dir", default=os.path.expanduser("~/jevsight-races"))
    ap.add_argument("--no-ui", action="store_true")
    ap.add_argument("--claude-config", default=CLEAN_CONFIG if os.path.isdir(CLEAN_CONFIG) else None,
                    help="CLAUDE_CONFIG_DIR for both sides (default ~/.jevsight-claude if it exists)")
    ap.add_argument("--allow-personal-config", action="store_true",
                    help="race with your normal ~/.claude setup (hooks, plugins, MCP servers) loaded")
    ap.add_argument("--server-cmd", "--neon-cmd", dest="server_cmd", help=argparse.SUPPRESS)  # e.g. "python3 tests/fake_mcp_server.py"
    ap.add_argument("--claude-cmd", default="claude", help=argparse.SUPPRESS)  # e.g. tests/fake_claude.py for a rehearsal
    a = ap.parse_args()
    # both sides run with cwd inside the run dir, so rehearsal paths must be absolute
    if "/" in a.claude_cmd:
        a.claude_cmd = os.path.abspath(a.claude_cmd)
    if a.server_cmd:
        a.server_cmd = " ".join(shlex.quote(os.path.abspath(t)) if os.path.exists(t) else t for t in shlex.split(a.server_cmd))
    if a.app is None:
        a.app = "fix" if os.path.isdir(APPS["fix"]["starter"]) else ("next" if os.path.isdir(APPS["next"]["starter"]) else "small")
    rehearsal = a.rehearsal = a.claude_cmd != "claude"
    if not rehearsal and not a.claude_config and not a.allow_personal_config:
        sys.exit("Races should not load your personal Claude Code setup (hooks, plugins, MCP servers, CLAUDE.md).\n"
                 "One-time setup, using your normal subscription login:\n"
                 "  CLAUDE_CONFIG_DIR=~/.jevsight-claude claude      # then run /login and quit\n"
                 "Or pass --allow-personal-config to race anyway.")
    if a.claude_config and not rehearsal:
        print("racing with clean Claude Code config: %s" % a.claude_config)
    if not rehearsal and not shutil.which("claude"):
        sys.exit("claude (Claude Code) is not on PATH")
    if APPS[a.app]["kind"] == "mcp":
        server_cmd(APPS[a.app], a)  # fail early if the key or token is missing
    os.makedirs(a.runs_dir, exist_ok=True)
    for i in range(1, a.repeat + 1):
        race_once(a, i)


if __name__ == "__main__":
    main()

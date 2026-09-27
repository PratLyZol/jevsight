#!/usr/bin/env python3
"""Jevsight MCP proxy: speculative execution for any stdio MCP server.

  python3 mcp_proxy.py -- npx -y @neondatabase/mcp-server-neon start <NEON_API_KEY>

Claude talks to this proxy as if it were the MCP server. Every message is relayed
unchanged, except:
  * after each tool result, Jev predicts the next tool call (tool name + arguments,
    with argument values taken from IDs that appeared in earlier results), and the
    proxy runs the read-only ones against the real server ahead of time when the
    expected-value rule says it pays;
  * when Claude then makes that exact call, the saved result is returned at once
    (or as soon as the early call finishes).
A call to any tool that is not on the read-only list throws away every early result.
If Jev is slow or down, calls are simply relayed: correctness never depends on Jev.

Only JSON-RPC ever goes to stdout. Diagnostics go to events.jsonl in $JEVSIGHT_DATA.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from common import data_dir, log_event, mode, opt  # noqa: E402
from predictor import PredictionError, make_predictor, render_state  # noqa: E402
from narration import default_tail, is_narration, n_tool_steps, narration_step, trace_steps  # noqa: E402

# Read-only tools, safe to run early. Neon's server does not publish readOnlyHint, so list them;
# tools that publish readOnlyHint=true are added automatically from tools/list.
READ_ONLY = {"list_projects", "list_shared_projects", "list_organizations", "describe_project", "describe_branch",
             "get_database_tables", "describe_table_schema", "list_branch_computes", "list_slow_queries"}
# Never run early, whatever any hint says: writes, money, secrets. `run_sql` with a plain SELECT is
# read-only in spirit, but a SELECT can still call setval()/pg_sleep() or `SELECT ... INTO`, so it
# stays here and also invalidates saved results when Claude calls it. Cheap and safe over clever.
NEVER = re.compile(r"(connection_string|create|delete|reset|provision|migration|tuning|run_sql)", re.I)
# Where to look in earlier results for a parameter's likely values.
PARAM_SOURCES = {
    # Neon
    "projectId": ["projectId", "project_id", "id"],
    "branchId": ["branchId", "branch_id", "default_branch_id", "id"],
    "databaseName": ["databaseName", "database_name", "name"],
    "tableName": ["tableName", "table_name"],
    "computeId": ["computeId", "compute_id", "id"],
    # GitHub (github-mcp-server): owner/repo come from "full_name": "owner/repo" in results
    "owner": ["owner", "repo_owner"],
    "repo": ["repo", "repo_name"],
    "path": ["path"],
    "sha": ["merge_commit_sha", "sha"],
    "ref": ["ref", "default_branch"],
    "issue_number": ["issue_number", "number"],
    "pullNumber": ["pullNumber", "pull_number", "number"],
    "tag": ["tag", "tag_name"],
    "org": ["org", "repo_owner"],
    # fetch-style servers: links in the last page, and the "start_index of N" hint for truncated pages
    "url": ["url", "link"],
    "start_index": ["start_index"],
    "max_length": [],
}
# Neon ids: projects look like proud-sun-12345678, branches br-cool-name-a1b2c3d4, computes ep-....
VALUE_FILTERS = {"url": re.compile(r"^https?://"), "start_index": re.compile(r"^\d{1,8}$"),
                 "projectId": re.compile(r"^(?!br-|ep-|org-)[a-z]+-[a-z]+-[a-z0-9]+$"),
                 "branchId": re.compile(r"^br-"), "computeId": re.compile(r"^ep-"),
                 "sha": re.compile(r"^[0-9a-f]{7,40}$"), "owner": re.compile(r"^[A-Za-z0-9-]{1,39}$"),
                 "repo": re.compile(r"^[A-Za-z0-9._-]{1,100}$"), "path": re.compile(r"^(?!https?://)[^\s]{1,200}$"),
                 "issue_number": re.compile(r"^\d{1,7}$"), "pullNumber": re.compile(r"^\d{1,7}$")}
KV = re.compile(r'"([A-Za-z_]+)"\s*:\s*"([^"\s]{1,100})"')
KV_NUM = re.compile(r'"([A-Za-z_]+)"\s*:\s*(\d{1,12})(?=[,}\s\]])')
SPLIT_KEYS = {"full_name": ("repo_owner", "repo_name")}   # "owner/repo" -> two values
# optional params whose value the *server* announces in a result (fetch: "start_index of 5000"); a candidate
# variant carrying that hint is built even though Claude has not used the param yet
HINT_PARAMS = {"start_index"}
LINK = re.compile(r'\]\((https?://[^)\s"]+)\)|<(https?://[^>\s"]+)>|(?<![\w"(])(https?://[^\s"<>)\]]+)')
START_INDEX = re.compile(r'start_index of (\d+)')
DEFAULT_BRANCH = [re.compile(r'"default_branch_id"\s*:\s*"(br-[^"]+)"'),
                  re.compile(r'"id"\s*:\s*"(br-[^"]+)"[^{}]*?"default"\s*:\s*true'),
                  re.compile(r'"default"\s*:\s*true[^{}]*?"id"\s*:\s*"(br-[^"]+)"')]
ACTIONS = {"call_tool": "calls another database tool", "finish": "stops and writes its final answer"}
ACTION_INSTR = "Given the agent's task and every tool call so far, what will it do next?"
CHOICE_INSTR = "If the agent calls another tool next, which exact call (tool name and JSON arguments) will it make?"
MAX_CANDIDATES = 254


def ewma(old, new, a=0.3):
    return new if old is None else (1 - a) * old + a * new


# ---------- pure helpers (shared with eval/replay_bench.py) ----------
def tool_props(tool):
    """(properties, required, wrapped) of a tool's input schema. Some servers (Neon) nest every
    argument under a single `params` object; that is unwrapped one level here."""
    schema = (tool or {}).get("inputSchema") or {}
    props = schema.get("properties") or {}
    p = props.get("params")
    if isinstance(p, dict) and isinstance(p.get("properties"), dict):
        return p["properties"], list(p.get("required") or []), True
    return props, list(schema.get("required") or []), False


def unwrap(args):
    """Flatten one level of `params`."""
    if isinstance(args, dict) and isinstance(args.get("params"), dict):
        out = {k: v for k, v in args.items() if k != "params"}
        out.update(args["params"])
        return out
    return dict(args or {})


def _is_default(prop, v):
    if not isinstance(prop, dict) or "default" not in prop:
        return False
    d = prop["default"]
    return d == v and isinstance(d, bool) == isinstance(v, bool)


def canon_args(tool, args):
    """Drop arguments that equal the schema default, and nulls. Keeps the `params` wrapper, so a
    call to a wrapped server never matches a flat one (a wrong hit is worse than a miss)."""
    props, _, _ = tool_props(tool)
    wrapped = isinstance(args, dict) and isinstance(args.get("params"), dict)
    inner = dict(args["params"]) if wrapped else dict(args or {})
    for k in list(inner):
        if inner[k] is None or _is_default(props.get(k), inner[k]):
            del inner[k]
    if wrapped:
        outer = {k: v for k, v in args.items() if k != "params"}
        outer["params"] = inner
        return outer
    return inner


def call_key(name, args, tool=None):
    a = canon_args(tool, args) if tool is not None else (args or {})
    return "%s %s" % (name, json.dumps(a, sort_keys=True, separators=(",", ":")))


def is_safe(name, read_only):
    return name in read_only and not NEVER.search(name or "")


def result_text(result):
    if not isinstance(result, dict):
        return str(result)
    parts = []
    for c in result.get("content") or []:
        if isinstance(c, dict) and c.get("type") == "text":
            parts.append(c.get("text", ""))
    if result.get("structuredContent") is not None:
        parts.append(json.dumps(result["structuredContent"]))
    return "\n".join(parts)


def response_text(resp):
    return result_text(resp.get("result")) if "result" in resp else json.dumps(resp.get("error"))


def extract_values(values, text, gens=None, gen=0):
    """Record `"key": "value"` pairs from a result. Lists are newest result first, and within one
    result in listing order (Claude tends to walk a list top to bottom). `gens` remembers the
    result number each value was last seen in."""
    batch = {}
    pairs = KV.findall(text) + KV_NUM.findall(text)
    if "://" in text:   # markdown/plain pages: links in reading order, without the fragment
        for m in LINK.finditer(text):
            u = (m.group(1) or m.group(2) or m.group(3)).rstrip(".,;:")
            u = u.split("#", 1)[0]
            if len(u) <= 300:
                pairs.append(("link", u))
    pairs += [("start_index", n) for n in START_INDEX.findall(text)]
    for k, v in pairs:
        batch.setdefault(k, [])
        if v not in batch[k]:
            batch[k].append(v)
        if k in SPLIT_KEYS and v.count("/") == 1:
            for kk, vv in zip(SPLIT_KEYS[k], v.split("/")):
                batch.setdefault(kk, [])
                if vv not in batch[kk]:
                    batch[kk].append(vv)
    for k, vs in batch.items():
        old = [x for x in values.get(k, []) if x not in vs]
        values[k] = (vs + old)[:64]
        if gens is not None:
            for v in vs:
                gens[v] = gen


def learn_default_branch(defaults, text, project_id):
    if not project_id:
        return
    for rx in DEFAULT_BRANCH:
        m = rx.search(text)
        if m:
            defaults[project_id] = m.group(1)
            return


def step_line(name, args, text, limit=300):
    return "%s(%s) -> %s" % (name, json.dumps(args, sort_keys=True)[:160], " ".join(text[:limit].split()) or "(empty)")


FULL_RESULT_CHARS = 1200   # the newest few results are shown to Jev at this length, older ones at 300


def tool_catalog(tools, read_only, limit=60):
    """One line per tool on the server: name, required args, whether it may be run early, description."""
    lines = []
    for name in sorted(tools):
        t = tools[name]
        _props, required, _wrap = tool_props(t)
        kind = "read-only" if is_safe(name, read_only) else "write or sensitive, never run early"
        desc = " ".join((t.get("description") or "").split())[:200]
        lines.append("- %s(%s) [%s]: %s" % (name, ", ".join(required) or "no required args", kind, desc))
    return lines[:limit]


def param_values(param, values, used_args, prop=None):
    """Likely values for a parameter: an enum's members if the schema has one; otherwise what Claude
    already used (latest first), then ids seen in results. Numbers are coerced for integer params."""
    prop = prop or {}
    if isinstance(prop.get("enum"), list) and prop["enum"]:
        used = [v for v in reversed(used_args.get(param, [])) if v in prop["enum"]]
        return used + [v for v in prop["enum"] if v not in used]
    vals = list(reversed(used_args.get(param, [])))
    for src in PARAM_SOURCES.get(param, [param]):
        for v in values.get(src, []):
            if v not in vals:
                vals.append(v)
    f = VALUE_FILTERS.get(param)
    if f:
        vals = [v for v in vals if isinstance(v, (str, int)) and f.search(str(v))]
    if prop.get("type") in ("integer", "number"):
        out = []
        for v in vals:
            try:  # ids are integers even when the schema says "number"; never turn 4840 into 4840.0
                n = int(v) if str(v).lstrip("-").isdigit() else float(v)
            except (TypeError, ValueError):
                continue
            if n not in out:
                out.append(n)
        vals = out
    return vals[:12]


def _words(name):
    return {w.rstrip("s") for w in (name or "").lower().split("_") if w not in ("get", "list", "read", "describe", "search")}


def build_candidates(tools, read_only, values, used_args, called=(), gens=None, limit=MAX_CANDIDATES, last_tool=None):
    """Every plausible next read-only call: (key, name, args). Ranked so that calls consuming an id
    from the newest result come first, more specific calls (more required ids) before generic ones,
    then by position in that result; calls already made come last, and a variant repeating Claude's
    earlier optional identifier args (branchId, ref) precedes the bare one. Jev sees the whole
    list; the order matters for the stand-in and the cap."""
    gens = gens or {}
    last_words = _words(last_tool)
    out, seen = [], set()
    for name in sorted(read_only):
        tool = tools.get(name)
        if tool is None or NEVER.search(name):
            continue
        affinity = -len(_words(name) & last_words)   # chains usually stay in one tool family
        props, required, wrap = tool_props(tool)
        combos = [({}, 0)]
        for r in required:
            vals = param_values(r, values, used_args, props.get(r))
            if not vals:
                combos = []
                break
            per = 24 if len(required) == 1 else 8
            combos = [(dict(c, **{r: v}), max(pos, i)) for c, pos in combos for i, v in enumerate(vals[:per])][:60]
        for c, pos in combos:
            # repeat Claude's earlier optional *identifier* args (branchId, ref, ...), never pagination or formatting
            # flags; an optional param with a fresh hint in the results (fetch's start_index) gets its own variant
            extra = {k: used_args[k][-1] for k in props
                     if k not in c and used_args.get(k) and k in PARAM_SOURCES and k not in HINT_PARAMS}
            variants = [(dict(c, **extra), 0), (c, 1)] if extra else [(c, 1)]
            for k in props:
                if k in c or k not in HINT_PARAMS:
                    continue
                hinted = [v for v in param_values(k, values, {}, props.get(k))[:1] if gens.get(str(v), -1) == max(gens.values(), default=-1)]
                if hinted and hinted[0] != extra.get(k):
                    variants.insert(0, (dict(c, **dict(extra, **{k: hinted[0]})), -1))
            for a, bare in variants:
                newest = max([gens.get(str(v), 0) for v in a.values()] or [-1])   # freshest id this call consumes
                a = {"params": a} if wrap else a
                key = call_key(name, a, tool)
                if key in seen:
                    continue
                seen.add(key)
                # newest id first, then the most specific call (more required ids), then listing position
                rank = (1 if key in called else 0, -newest, affinity, -len(required), pos, bare, name, key)
                out.append((rank, key, name, a))
    out.sort(key=lambda x: x[0])
    return [(k, n, a) for _, k, n, a in out[:limit]]


def alias_args(tool, args, default_branch):
    """The one equivalent spelling we accept: `branchId` omitted <-> set to the project's default
    branch, only when the schema marks branchId optional. Returns None when there is no alias."""
    props, required, wrap = tool_props(tool)
    if "branchId" not in props or "branchId" in required:
        return None
    inner = unwrap(canon_args(tool, args))
    dflt = default_branch.get(inner.get("projectId"))
    if not dflt:
        return None
    if "branchId" not in inner:
        alt = dict(inner, branchId=dflt)
    elif inner.get("branchId") == dflt:
        alt = {k: v for k, v in inner.items() if k != "branchId"}
    else:
        return None
    return {"params": alt} if wrap else alt


# ---------- the proxy ----------
class Job:
    def __init__(self, key, name, args, version, p, ev):
        self.key, self.name, self.args, self.version, self.p, self.ev = key, name, args, version, p, ev
        self.id = "jevsight-" + uuid.uuid4().hex[:10]
        self.start = time.time()
        self.end = None
        self.response = None
        self.done = asyncio.get_running_loop().create_future()
        self.used_at = None


UPSTREAM_GONE = {"code": -32000, "message": "jevsight: upstream MCP server exited"}


class Proxy:
    def __init__(self, upstream_cmd):
        self.upstream_cmd = upstream_cmd
        self.task = opt("task") or ""
        self.tools = {}
        self.read_only = set(READ_ONLY) | {n.strip() for n in (opt("read_only") or "").split(",") if n.strip()}
        self.pending = {}      # upstream request id -> (method, name, args, t_sent)
        self.serving = {}      # client request id -> asyncio.Task answering it from a saved result
        self.spec = {}         # job id -> Job
        self.by_key = {}       # call key -> Job (current version only)
        self.version = 0
        self.steps = []        # short trace lines (tool calls and Claude's narration)
        self.steps_full = []   # same lines, results at full length (the newest few are shown that way)
        self.values = {}       # result key -> values seen, newest result first
        self.used_args = {}    # param -> values Claude used, oldest first
        self.called = set()    # canonical keys Claude has called (and their alias spellings)
        self.gens = {}         # value -> number of the result it was last seen in
        self.last_tool = None
        self.default_branch = {}  # projectId -> default branch id
        self.tool_time = {}
        self.think = None
        self.last_result_ts = None
        self.pred_seq = 0
        self.last_pred = None
        self.pred_before = None   # prediction made before Claude's latest narration, kept for the outcome log
        self.narrated = False     # the next prediction was triggered by narration
        self.tail = default_tail(time.time())
        self.up = None
        self.up_dead = False
        self.predictor = make_predictor()
        if self.task:  # ids and links the task itself names are candidates from the start (generation 0)
            extract_values(self.values, self.task, self.gens, 0)
        self.alpha = float(opt("alpha", "0.25") or 0.25)
        self.max_launch = int(opt("max_launch", "2") or 2)
        self.out_lock = asyncio.Lock()
        self.up_lock = asyncio.Lock()
        log_event("daemon_start", predictor=self.predictor.name, mode=mode(), component="mcp_proxy",
                  upstream=" ".join(upstream_cmd[:3]))

    # ---------- plumbing ----------
    async def send_client(self, msg):
        async with self.out_lock:
            sys.stdout.write(json.dumps(msg) + "\n")
            sys.stdout.flush()

    async def send_upstream(self, msg):
        if self.up_dead:
            raise ConnectionError("upstream gone")
        async with self.up_lock:
            try:
                self.up.stdin.write((json.dumps(msg) + "\n").encode())
                await self.up.stdin.drain()
            except (BrokenPipeError, ConnectionResetError, OSError) as e:
                self.up_dead = True
                raise ConnectionError(str(e))

    async def run(self):
        self.up = await asyncio.create_subprocess_exec(*self.upstream_cmd, stdin=asyncio.subprocess.PIPE,
                                                       stdout=asyncio.subprocess.PIPE, stderr=sys.stderr,
                                                       limit=2 ** 26)
        asyncio.ensure_future(self.watch_narration(self.pred_seq))
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader(limit=2 ** 26)
        await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
        await asyncio.gather(self.client_loop(reader), self.upstream_loop())

    async def client_loop(self, reader):
        while True:
            line = await reader.readline()
            if not line:
                try:
                    self.up.stdin.close()
                except OSError:
                    pass
                return
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            method = msg.get("method")
            if method == "tools/call" and "id" in msg:
                # registered before the task runs, so a cancel that is already buffered finds it
                self.serving[msg["id"]] = asyncio.ensure_future(self.on_client_call(msg))
            elif method == "notifications/cancelled":
                await self.on_cancel(msg)
            else:
                if "id" in msg and method:
                    self.pending[msg["id"]] = (method, None, None, time.time())
                try:
                    await self.send_upstream(msg)
                except ConnectionError:
                    if "id" in msg and method:
                        self.pending.pop(msg["id"], None)
                        await self.send_client({"jsonrpc": "2.0", "id": msg["id"], "error": UPSTREAM_GONE})

    async def upstream_loop(self):
        while True:
            line = await self.up.stdout.readline()
            if not line:
                await self.upstream_gone()
                return
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            mid = msg.get("id")
            if mid in self.spec and "method" not in msg:
                self.finish_job(self.spec.pop(mid), msg)
                continue
            if mid in self.pending and "method" not in msg:
                method, name, args, t0 = self.pending.pop(mid)
                if method == "tools/list":
                    self.learn_tools(msg)
                elif method == "tools/call":
                    dur = time.time() - t0
                    self.tool_time[name] = ewma(self.tool_time.get(name), dur)
                    await self.send_client(msg)
                    self.after_result(name, args, msg)
                    continue
            await self.send_client(msg)

    async def upstream_gone(self):
        """Upstream closed its stdout: answer everything still open with an error, then exit."""
        self.up_dead = True
        for job in list(self.spec.values()):
            if not job.done.done():
                job.done.set_result({"error": dict(UPSTREAM_GONE)})
        await asyncio.sleep(0.05)  # let tasks that were waiting on a job reply
        for rid, (method, _, _, _) in list(self.pending.items()):
            await self.send_client({"jsonrpc": "2.0", "id": rid, "error": dict(UPSTREAM_GONE)})
        self.pending.clear()
        log_event("daemon_stop", component="mcp_proxy", reason="upstream_exit")
        try:
            rc = await asyncio.wait_for(self.up.wait(), 2.0)
        except asyncio.TimeoutError:
            rc = 0
        sys.stdout.flush()
        os._exit(rc or 0)

    def learn_tools(self, msg):
        for t in (msg.get("result") or {}).get("tools") or []:
            self.tools[t["name"]] = t
            if (t.get("annotations") or {}).get("readOnlyHint") and not NEVER.search(t["name"]):
                self.read_only.add(t["name"])
        try:  # for eval/replay_bench.py, which rebuilds candidates offline with the same schemas
            with open(os.path.join(data_dir(), "tools.json"), "w") as f:
                json.dump({"tools": list(self.tools.values()), "read_only": sorted(self.read_only)}, f)
        except OSError:
            pass

    def safe(self, name):
        return is_safe(name, self.read_only)

    def key(self, name, args):
        return call_key(name, args, self.tools.get(name))

    # ---------- Claude's calls ----------
    async def on_client_call(self, msg):
        cid = msg["id"]
        try:
            await self.handle_call(msg)
        except asyncio.CancelledError:
            pass  # logged by on_cancel; the reply is simply not sent
        except ConnectionError:
            await self.send_client({"jsonrpc": "2.0", "id": cid, "error": dict(UPSTREAM_GONE)})
        finally:
            self.serving.pop(cid, None)

    async def on_cancel(self, msg):
        rid = (msg.get("params") or {}).get("requestId")
        task = self.serving.pop(rid, None)
        if task is not None and task is not asyncio.current_task():
            task.cancel()   # the reply was going to come from a saved result: just drop it
            log_event("cancelled", request=str(rid))
            return
        try:
            await self.send_upstream(msg)  # upstream saw the request; let it see the cancel too
        except ConnectionError:
            pass

    async def relay(self, msg, name, args, now):
        self.serving.pop(msg["id"], None)  # from here on a cancel is forwarded upstream
        self.pending[msg["id"]] = ("tools/call", name, args, now)
        try:
            await self.send_upstream(msg)
        except ConnectionError:
            self.pending.pop(msg["id"], None)
            raise

    def lookup(self, name, args, key):
        job = self.by_key.get(key)
        if job is not None:
            return job, False
        alt = alias_args(self.tools.get(name), args, self.default_branch)
        if alt is not None:
            job = self.by_key.get(self.key(name, alt))
            if job is not None:
                return job, True
        return None, False

    async def handle_call(self, msg):
        params = msg.get("params") or {}
        name, args = params.get("name"), params.get("arguments") or {}
        key = self.key(name, args)
        now = time.time()
        if self.last_result_ts:
            self.think = ewma(self.think, now - self.last_result_ts)
        self.absorb_narration(inflight=True)   # what Claude said just before this call belongs before it
        self.resolve_prediction(key)
        for k, v in unwrap(args).items():
            if isinstance(v, (str, int, float, bool)):
                lst = self.used_args.setdefault(k, [])
                if v in lst:
                    lst.remove(v)
                lst.append(v)
        self.called.add(key)
        alt = alias_args(self.tools.get(name), args, self.default_branch)
        if alt is not None:
            self.called.add(self.key(name, alt))
        if not self.safe(name):
            self.invalidate("write:%s" % name)
            await self.relay(msg, name, args, now)
            return
        job, aliased = self.lookup(name, args, key)
        if mode() == "on" and job is not None and job.version == self.version:
            job.used_at = now
            log_event("hit", cmd=key, job=job.id, job_status="done" if job.end else "running",
                      p=round(job.p, 4), head_start_s=round(now - job.start, 3), alias=aliased)
            try:
                resp = await job.done
            except asyncio.CancelledError:
                job.used_at = None
                raise
            if "error" in resp:  # never serve a saved error (it may have been transient): ask live
                job.used_at = None
                log_event("miss", cmd=key, had_job=True, reason="job_error")
                await self.relay(msg, name, args, now)
                return
            dur = (job.end or time.time()) - job.start
            log_event("saved", cmd=key, job=job.id, saved_s=round(max(0.0, min(dur, now - job.start)), 3),
                      dur_s=round(dur, 3))
            await self.send_client({"jsonrpc": "2.0", "id": msg["id"], "result": resp.get("result")})
            self.after_result(name, args, resp)
            return
        log_event("miss", cmd=key, had_job=job is not None)
        await self.relay(msg, name, args, now)

    def invalidate(self, why):
        self.version += 1
        for key, job in list(self.by_key.items()):
            if job.end is None:
                log_event("wasted", cmd=key, job=job.id, wasted_s=round(time.time() - job.start, 3), reason="stale:" + why)
            elif job.used_at is None:
                log_event("wasted", cmd=key, job=job.id, wasted_s=round(job.end - job.start, 3), reason="stale:" + why)
        self.by_key.clear()

    def after_result(self, name, args, resp):
        text = response_text(resp)
        self.last_tool = name
        extract_values(self.values, text, self.gens, n_tool_steps(self.steps) + 1)
        if name == "describe_project":
            learn_default_branch(self.default_branch, text, unwrap(args).get("projectId"))
        self.absorb_narration(inflight=True)
        self.add_step(step_line(name, args, text), step_line(name, args, text, FULL_RESULT_CHARS))
        self.last_result_ts = self.last_step_ts = time.time()
        self.schedule_prediction()

    def add_step(self, short, full=None):
        self.steps.append(short)
        self.steps_full.append(full or short)
        self.steps, self.steps_full = self.steps[-200:], self.steps_full[-200:]

    def schedule_prediction(self):
        self.pred_seq += 1
        asyncio.ensure_future(self.predict_and_launch(self.pred_seq))
        asyncio.ensure_future(self.watch_narration(self.pred_seq))

    # ---------- Claude's narration ----------
    def absorb_narration(self, inflight=False):
        """Add what Claude has said since the last poll. `inflight`: a call is being handled right
        now, so the words belong to it and go at the end. Otherwise words that came with a call
        whose result is already the last step (transcript source) go back in front of that step.
        Returns True if any of the words look ahead to a call not made yet."""
        ahead = False
        for it in self.tail.poll():
            line = narration_step(it["text"])
            j = None if inflight else self.place_before(it.get("then_tool"))
            if j is None:
                self.add_step(line)
                ahead = ahead or not it.get("then_tool")
            else:
                self.steps.insert(j, line)
                self.steps_full.insert(j, line)
            log_event("narration", text=it["text"][:200], n_calls=n_tool_steps(self.steps),
                      with_call=it.get("then_tool"), placed="before_last_step" if j is not None else "end")
        return ahead

    def place_before(self, then_tool):
        if not then_tool:
            return None
        short = then_tool.split("__")[-1]
        for j in range(len(self.steps) - 1, -1, -1):
            if is_narration(self.steps[j]):
                continue
            recent = time.time() - (getattr(self, "last_step_ts", 0) or 0) < 5.0
            return j if recent and self.steps[j].startswith(short + "(") else None
        return None

    async def watch_narration(self, seq):
        """While Claude thinks after a result, watch the transcript: as soon as Claude narrates its
        next move, predict again with those words in the state."""
        deadline = time.time() + 45.0
        while time.time() < deadline and seq == self.pred_seq and not self.up_dead:
            await asyncio.sleep(0.15)
            if seq != self.pred_seq:
                return
            if self.absorb_narration():
                self.narrated = True
                self.schedule_prediction()
                return

    # ---------- prediction ----------
    def candidates(self):
        return build_candidates(self.tools, self.read_only, self.values, self.used_args, self.called, self.gens,
                                last_tool=self.last_tool)

    async def predict_and_launch(self, seq):
        # a result may be one of several landing together: wait a moment. Narration is a single
        # event that arrives 0.3-0.5s before the call it announces: no time to spare.
        await asyncio.sleep(0.0 if self.narrated else float(opt("debounce", "0.15") or 0.15))
        if seq != self.pred_seq or mode() == "off" or self.up_dead:
            return
        cands = self.candidates()
        if not cands:
            return
        keys = [k for k, _, _ in cands]
        narrated, self.narrated = self.narrated, False
        facts = {"tool_calls_so_far": n_tool_steps(self.steps),
                 "ids_seen_so_far": ", ".join(sorted({v for vs in self.values.values() for v in vs[:3]}))[:600]}
        sections = [("TOOLS ON THIS MCP SERVER (name(required args) [may it be run early]: what it does):",
                     tool_catalog(self.tools, self.read_only))] if self.tools else None
        state = render_state(self.task, trace_steps(self.steps, self.steps_full), facts, sections)
        t0 = time.time()
        try:
            pred = await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.predictor.predict_generic(state, ACTIONS, "call_tool", keys, ACTION_INSTR, CHOICE_INSTR))
        except PredictionError as e:
            log_event("predict_error", error=str(e)[:300], predictor=self.predictor.name)
            return
        if seq != self.pred_seq:
            return
        probs = pred["commands"]
        ranked = sorted(probs.items(), key=lambda kv: -kv[1])
        think = self.think if self.think is not None else 3.0
        if self.last_result_ts:  # part of the thinking gap has already passed (Jev latency, narration wait)
            think = max(0.2, think - (time.time() - self.last_result_ts))
        by = {k: (n, a) for k, n, a in cands}
        decisions, launched = [], 0
        for key, p in ranked[:10]:
            if key not in by:
                continue
            name, args = by[key]
            t = self.tool_time.get(name, 1.0)
            ev = p * min(t, think) - (1 - p) * self.alpha * t
            d = "skip"
            if ev > 0 and launched < self.max_launch:
                if key in self.by_key:
                    d = "have"
                elif mode() == "on":
                    job = Job(key, name, args, self.version, p, ev)
                    self.spec[job.id] = job
                    self.by_key[key] = job
                    try:
                        await self.send_upstream({"jsonrpc": "2.0", "id": job.id, "method": "tools/call",
                                                  "params": {"name": name, "arguments": args}})
                    except ConnectionError:
                        self.spec.pop(job.id, None)
                        self.by_key.pop(key, None)
                        return
                    log_event("launch", cmd=key, job=job.id, p=round(p, 4), ev=round(ev, 3), version=self.version)
                    d = "launch"
                    launched += 1
                else:
                    d = "would_launch"
                    launched += 1
            decisions.append({"cmd": key, "p": round(p, 4), "ev": round(ev, 3), "decision": d})
        if narrated and self.last_pred is not None:
            self.pred_before = self.last_pred
        self.last_pred = {"id": uuid.uuid4().hex[:10], "probs": probs, "p_run": pred.get("p_run", 0.0),
                          "launch": [d["cmd"] for d in decisions if d["decision"] in ("launch", "have", "would_launch")],
                          "narrated": narrated}
        log_event("predict", pred=self.last_pred["id"], predictor=self.predictor.name, route=pred.get("route"),
                  latency_s=round(time.time() - t0, 3), p_run=round(pred.get("p_run", 0.0), 4),
                  top=decisions[:5], n_candidates=len(cands), version=self.version, after_narration=narrated,
                  supersedes=(self.pred_before or {}).get("id") if narrated else None)

    def resolve_prediction(self, actual_key):
        pr, before = self.last_pred, self.pred_before
        self.last_pred = self.pred_before = None
        self.narrated = False
        if not pr:
            return
        extra = {}
        if before:
            extra = {"p_actual_before_narration": round(before["probs"].get(actual_key, 0.0), 4),
                     "would_hit_before_narration": actual_key in before["launch"]}
        log_event("outcome", pred=pr["id"], actual_kind="run_command", actual_cmd=actual_key,
                  p_actual=round(pr["probs"].get(actual_key, 0.0), 4), p_run=round(pr["p_run"], 4),
                  probs={k: round(v, 4) for k, v in sorted(pr["probs"].items(), key=lambda kv: -kv[1])[:10]},
                  would_hit=actual_key in pr["launch"], after_narration=pr.get("narrated", False), **extra)

    def finish_job(self, job, msg):
        job.end = time.time()
        job.response = msg
        dur = job.end - job.start
        self.tool_time[job.name] = ewma(self.tool_time.get(job.name), dur)
        log_event("job_done", cmd=job.key, job=job.id, rc=0 if "result" in msg else 1, dur_s=round(dur, 3), status="done")
        if not job.done.done():
            job.done.set_result(msg)


def main():
    argv = sys.argv[1:]
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    if not argv:
        sys.exit("usage: mcp_proxy.py -- <upstream MCP server command...>")
    asyncio.run(Proxy(argv).run())


if __name__ == "__main__":
    main()

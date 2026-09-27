#!/usr/bin/env python3
"""Jevsight agent: a tool-calling loop on the Anthropic Messages API where Jev takes the routine turns.

After every tool result, Jev (TypeSafe's calibrated classifier) is asked which exact read-only call comes next. When its
top answer clears --threshold, this loop makes the call itself and writes it into the transcript as if the model had
asked for it; the model (Claude) is only called when Jev is unsure, when the work is done, or when the next step is not
a choice from a list. Same tool calls, same answer, about half the model turns.

  python3 jevagent.py --mcp-json .mcp.json --name fetch --task "Read these pages and write a cheat sheet: ..."
  python3 jevagent.py --server "uvx mcp-server-fetch" --read-only fetch --task "..."

Needs ANTHROPIC_API_KEY and a Jev key (AI_GATEWAY_API_KEY, OPENROUTER_API_KEY or JEVSIGHT_API_KEY) in the environment
or in ./.env. Only read-only tools are ever called by Jev: tools that publish readOnlyHint, names on --read-only, and
(unless --strict) names that start with get/list/read/describe/search/fetch/find/show; never anything on the
never-list (create/delete/reset/provision/migration/tuning/run_sql/connection_string).
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import shlex
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import mcp_proxy as mp  # noqa: E402
from mcp_client import Client  # noqa: E402
from predictor import PredictionError, make_predictor, render_state, ssl_context  # noqa: E402

try:
    from narration import narration_step
except ImportError:
    def narration_step(text):
        return "Claude says: " + " ".join(text.split())[:400]

SYSTEM = ("You are a careful research agent. Use the tools to read what the task asks for, one call at a time, "
          "then write the deliverable in markdown. Some tool calls in the conversation may have been made on your "
          "behalf by a fast predictor; their results are real and yours to use, so do not repeat them.")
ANTHROPIC_HOST = "api.anthropic.com"
PAGE_ARGS = {"max_length": 40000, "perPage": 50}
URL_RX = re.compile(r'"url"\s*:\s*"[^"]*/([^/"]+?)(?:\.html)?"(?=[,}])')
READ_ONLY_NAME = re.compile(r"^(get|list|read|describe|search|fetch|find|show|query_logs|inspect)(_|$)", re.I)


def load_dotenv(path=".env"):
    """KEY=value lines into os.environ, without overriding what is already set. Never prints values."""
    try:
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))
    except OSError:
        pass


SMALL_SUFFIX = ("\n\nYou are the navigation stage only: fetch the pages (and the rest of any truncated page) one call at a time. "
                "Do not write the cheat sheet or summarise anything. As soon as every page has been read in full, reply with "
                "the single word DONE and nothing else; a stronger model will write the answer from the pages you fetched.")


class Claude:
    """Minimal Messages API client with retries on overload."""

    def __init__(self, model, key, max_tokens=8000, cache=True):
        self.model, self.key, self.max_tokens, self.cache = model, key, max_tokens, cache
        self.calls, self.seconds, self.in_tokens, self.out_tokens = 0, 0.0, 0, 0
        self.cache_write, self.cache_read = 0, 0   # prompt-cache tokens written / read (billed 1.25x / 0.1x)

    @staticmethod
    def _with_breakpoints(system, messages, tools):
        """Prompt caching: one breakpoint after the system prompt + tools, one on the last message, so every turn
        re-reads the previous turn's prefix from cache instead of paying for it again."""
        cc = {"cache_control": {"type": "ephemeral"}}
        system = [{"type": "text", "text": system, **cc}]
        tools = [dict(t) for t in tools]
        if tools:
            tools[-1] = {**tools[-1], **cc}
        messages = [dict(m) for m in messages]
        last = messages[-1]
        content = last["content"]
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        content = [dict(b) for b in content]
        content[-1] = {**content[-1], **cc}
        messages[-1] = {**last, "content": content}
        return system, messages, tools

    def __call__(self, system, messages, tools):
        if self.cache:
            system, messages, tools = self._with_breakpoints(system, messages, tools)
        body = {"model": self.model, "max_tokens": self.max_tokens, "system": system, "messages": messages, "tools": tools}
        data = json.dumps(body).encode()
        delay, last = 2.0, None
        for attempt in range(6):
            t0 = time.time()
            conn = http.client.HTTPSConnection(ANTHROPIC_HOST, timeout=180, context=ssl_context())
            try:
                conn.request("POST", "/v1/messages", body=data, headers={
                    "x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
                r = conn.getresponse()
                raw = r.read()
            except (OSError, http.client.HTTPException) as e:
                last = "network: %s" % e
                r = None
            finally:
                conn.close()
            self.seconds += time.time() - t0
            if r is not None and r.status == 200:
                out = json.loads(raw)
                self.calls += 1
                u = out.get("usage") or {}
                self.in_tokens += u.get("input_tokens", 0)
                self.out_tokens += u.get("output_tokens", 0)
                self.cache_write += u.get("cache_creation_input_tokens", 0) or 0
                self.cache_read += u.get("cache_read_input_tokens", 0) or 0
                return out
            if r is not None:
                last = "HTTP %s: %s" % (r.status, raw[:200].decode(errors="replace"))
                if r.status not in (429, 529) and r.status < 500:
                    raise RuntimeError("Claude call failed: " + last)
            print("  claude: %s; retry in %.0fs" % (last, delay))
            time.sleep(delay)
            delay *= 2
        raise RuntimeError("Claude call failed after retries: %s" % last)

    def totals(self):
        """input_tokens = every token the model was shown; input_equiv = what that costs in uncached-token units
        (cache writes bill at 1.25x, cache reads at 0.1x), so runs with and without caching compare on one axis."""
        return {"turns": self.calls, "seconds": round(self.seconds, 2), "output_tokens": self.out_tokens,
                "uncached_input_tokens": self.in_tokens, "cache_write_tokens": self.cache_write,
                "cache_read_tokens": self.cache_read, "input_tokens": self.in_tokens + self.cache_write + self.cache_read,
                "input_equiv_tokens": round(self.in_tokens + 1.25 * self.cache_write + 0.1 * self.cache_read)}


def anthropic_tools(mcp_tools, allowed):
    out = []
    for t in mcp_tools:
        if t["name"] not in allowed:
            continue
        schema = t.get("inputSchema") or {"type": "object", "properties": {}}
        out.append({"name": t["name"], "description": (t.get("description") or "")[:1000], "input_schema": schema})
    return out


def text_of(result):
    return mp.result_text(result)


class Run:
    def __init__(self, a, driver, run_dir, on_event=None):
        """on_event(record): called with every trace record as it is written (the web UI streams these)."""
        self.a, self.driver, self.run_dir, self.on_event = a, driver, run_dir, on_event
        os.makedirs(run_dir, exist_ok=True)
        self.trace = open(os.path.join(run_dir, "trace.jsonl"), "w")
        self.app = {"read_only": a.read_only, "verify_from": "args", "verify_rx": URL_RX}
        self.prompt = a.task
        self.steps, self.values, self.gens, self.used_args, self.called, self.default_branch = [], {}, {}, {}, set(), {}
        mp.extract_values(self.values, self.prompt, self.gens, 0)
        self.tool_time = self.jev_time = self.jev_cost = 0.0   # jev_cost: USD as billed by the gateway, when reported
        self.tool_calls = self.jev_calls = self.jev_errors = self.jev_commits = self.jev_declined = 0
        self.last_tool = None
        self.n = 0

    def log(self, **rec):
        rec["t"] = round(time.time() - self.t0, 3)
        self.trace.write(json.dumps(rec) + "\n")
        self.trace.flush()
        if self.on_event:
            try:
                self.on_event(rec)
            except Exception as e:  # a UI listener must never break a run
                print("  on_event: %s" % e)

    def start_server(self):
        cmd, senv = self.a.server_cmd, self.a.server_env
        env = dict(os.environ, **senv)
        self.mcp = Client(cmd, env, cwd=self.run_dir)
        self.mcp.handshake("jevloop")
        rid = self.mcp.send("tools/list")
        m = self.mcp.read(60)
        self.tools = {t["name"]: t for t in m["result"]["tools"]}
        allowed = set(mp.READ_ONLY) | {n.strip() for n in (self.app.get("read_only") or "").split(",") if n.strip()}
        for t in self.tools.values():
            if (t.get("annotations") or {}).get("readOnlyHint") and not mp.NEVER.search(t["name"]):
                allowed.add(t["name"])
            elif self.a.infer_read_only and READ_ONLY_NAME.match(t["name"]) and not mp.NEVER.search(t["name"]):
                allowed.add(t["name"])   # no hint published: a conservative name rule, shown to the user below
        self.allowed = {n for n in allowed if n in self.tools and mp.is_safe(n, allowed)}
        if not self.allowed:
            raise RuntimeError("no read-only tools available from %s" % cmd[0])

    def execute(self, name, args, who):
        """Run one tool call on the MCP server, record it the way the proxy would."""
        if name not in self.allowed:
            return "tool %s is not allowed in this read-only run" % name, True, 0.0
        t0 = time.time()
        msg, _ = self.mcp.call(name, args, timeout=120)
        dur = time.time() - t0
        self.tool_time += dur
        self.tool_calls += 1
        err = "error" in msg or bool((msg.get("result") or {}).get("isError"))
        text = mp.response_text(msg)
        for k, v in mp.unwrap(args).items():
            if isinstance(v, (str, int, float, bool)):
                lst = self.used_args.setdefault(k, [])
                if v in lst:
                    lst.remove(v)
                lst.append(v)
        key = mp.call_key(name, args, self.tools.get(name))
        self.called.add(key)
        alt = mp.alias_args(self.tools.get(name), args, self.default_branch)
        if alt is not None:
            self.called.add(mp.call_key(name, alt, self.tools.get(name)))
        self.last_tool = name
        mp.extract_values(self.values, text, self.gens, len(self.steps) + 1)
        if name == "describe_project":
            mp.learn_default_branch(self.default_branch, text, mp.unwrap(args).get("projectId"))
        self.steps.append(mp.step_line(name, args, text))
        self.log(kind="tool", who=who, tool=name, args=args, seconds=round(dur, 3), chars=len(text), error=err)
        print("  %-6s %-5.2fs %s %s%s" % (who, dur, name, json.dumps(args)[:80], "  ERROR" if err else ""))
        return text, err, dur

    def jev_next(self):
        """Ask Jev for the next call. Returns (key, name, args, p) or None."""
        cands = mp.build_candidates(self.tools, self.allowed, self.values, self.used_args, self.called, self.gens,
                                    last_tool=self.last_tool)
        if not cands:
            return None
        keys = [k for k, _, _ in cands]
        facts = {"tool_calls_so_far": self.tool_calls,
                 "ids_seen_so_far": ", ".join(sorted({v for vs in self.values.values() for v in vs[:3]}))[:600]}
        state = render_state(self.prompt, self.steps[-200:], facts)
        t0 = time.time()
        try:
            pred = self.predictor.predict_generic(state, mp.ACTIONS, "call_tool", keys, mp.ACTION_INSTR, mp.CHOICE_INSTR)
        except PredictionError as e:
            self.jev_time += time.time() - t0
            self.jev_errors += 1
            self.log(kind="jev_error", error=str(e)[:200])
            print("  jev    error: %s" % str(e)[:80])
            return None
        self.jev_time += time.time() - t0
        self.jev_calls += 1
        probs = pred["commands"]
        top = max(probs, key=probs.get) if probs else None
        p = probs.get(top, 0.0) if top else 0.0
        by = {k: (n, a) for k, n, a in cands}
        if pred.get("cost_usd") is not None:
            self.jev_cost += pred["cost_usd"]
        ranked = sorted(probs.items(), key=lambda kv: -kv[1])[:6]
        self.log(kind="jev", p_call_tool=round(pred.get("p_run", 0.0), 3), top=top, p_top=round(p, 3),
                 n_candidates=len(cands), latency=round(time.time() - t0, 3), route=pred.get("route"),
                 usage=pred.get("usage"), cost_usd=pred.get("cost_usd"),
                 top5=[{"cmd": k, "p": round(v, 3), "seen": k in self.called} for k, v in ranked],
                 threshold=self.a.threshold)
        if top is None or top not in by:
            return None
        name, args = by[top]
        return top, name, args, p

    def run(self):
        self.t0 = time.time()
        self.log(kind="start", driver=self.driver, model=self.a.model, app=self.a.server_name, task=self.prompt[:2000],
                 small_model=self.a.small_model if self.driver == "cascade" else None, threshold=self.a.threshold,
                 cache=bool(self.a.cache))
        self.predictor = make_predictor() if self.driver == "jev" else None
        self.start_server()
        claude = Claude(self.a.model, os.environ["ANTHROPIC_API_KEY"], cache=self.a.cache)
        small = (Claude(self.a.small_model, os.environ["ANTHROPIC_API_KEY"], max_tokens=self.a.small_max_tokens, cache=self.a.cache)
                 if self.driver == "cascade" else None)
        escalated = small is None
        tools = anthropic_tools(self.tools.values(), self.allowed)
        messages = [{"role": "user", "content": self.prompt}]
        answer, turns, chain = "", 0, 0
        print("== %s driver, model %s%s, read-only tools: %s, run dir %s" % (
            self.driver, self.a.model, (" (navigation: %s)" % self.a.small_model) if small else "", ", ".join(sorted(self.allowed)), self.run_dir))
        while True:
            # --- Jev's turn(s): only in the jev driver, only right after a tool result
            if self.driver == "jev" and self.steps and chain < self.a.max_chain:
                nxt = self.jev_next()
                if nxt is not None and nxt[3] >= self.a.threshold and nxt[0] not in self.called:
                    key, name, args, p = nxt
                    props, _, wrap = mp.tool_props(self.tools.get(name))
                    inner = args["params"] if wrap else args
                    for k, v in PAGE_ARGS.items():
                        if k in props and k not in inner:
                            biggest = max([x for x in self.used_args.get(k, []) if isinstance(x, (int, float))] or [v])
                            inner[k] = max(v, biggest) if k == "max_length" else biggest
                    self.jev_commits += 1
                    chain += 1
                    tid = "toolu_jev_%03d" % self.jev_commits
                    text, err, dur = self.execute(name, args, "jev")
                    self.log(kind="commit", p=round(p, 3), key=key)
                    messages.append({"role": "assistant", "content": [{"type": "tool_use", "id": tid, "name": name, "input": args}]})
                    messages.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": text, "is_error": err}]})
                    if err:
                        chain = self.a.max_chain   # do not let Jev keep going after an error: give Claude the turn
                    continue
                if nxt is not None:
                    self.jev_declined += 1
            chain = 0
            # --- Claude's turn (in the cascade driver the small model's turn until it stops calling tools)
            model = claude if escalated else small
            who = "claude" if model is claude else "small"
            t0 = time.time()
            out = model(SYSTEM if model is claude else SYSTEM + SMALL_SUFFIX, messages, tools)
            turns += 1
            dur = time.time() - t0
            blocks = out.get("content") or []
            texts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
            uses = [b for b in blocks if b.get("type") == "tool_use"]
            self.log(kind=who, turn=turns, seconds=round(dur, 3), stop=out.get("stop_reason"), tool_uses=len(uses),
                     text=" ".join(texts)[:300], usage=out.get("usage"), model=model.model)
            print("  %-6s %-5.1fs turn %d: %d tool call(s)%s" % (who, dur, turns, len(uses), ("  \"" + " ".join(texts)[:70] + "\"") if texts else ""))
            if not uses and not escalated:
                # the small model thinks navigation is over: drop its write-up and give the transcript to the big model
                escalated = True
                self.log(kind="escalate", turn=turns, discarded_chars=len(" ".join(texts)))
                print("  escalate: navigation done after %d small-model turns; %s writes the answer" % (turns, self.a.model))
                continue
            for t in texts:
                if t.strip():
                    self.steps.append(narration_step(t))
            messages.append({"role": "assistant", "content": blocks})
            if not uses:
                answer = "\n\n".join(texts)
                break
            results = []
            for u in uses:
                text, err, dur = self.execute(u["name"], u.get("input") or {}, "claude")
                results.append({"type": "tool_result", "tool_use_id": u["id"], "content": text, "is_error": err})
            messages.append({"role": "user", "content": results})
            if turns >= self.a.max_turns:
                answer = "(stopped after %d turns)" % turns
                break
        wall = time.time() - self.t0
        self.mcp.close()
        self.trace.close()
        with open(os.path.join(self.run_dir, "answer.md"), "w") as f:
            f.write(answer)
        pages = []
        for line in open(os.path.join(self.run_dir, "trace.jsonl")):
            r = json.loads(line)
            if r.get("kind") == "tool" and self.app.get("verify_from") == "args":
                for m in self.app["verify_rx"].findall(json.dumps({"url": mp.unwrap(r["args"]).get("url", "")})):
                    if m not in pages:
                        pages.append(m)
        low = answer.lower()
        named = [p for p in pages if p.lower() in low or (("-" in p) and p.rsplit("-", 1)[-1].lower() in low)]
        per_model = {claude.model: claude.totals()}
        if small is not None:
            per_model[small.model] = small.totals()
        clients = [c for c in (claude, small) if c is not None]
        tot = lambda k: sum(c.totals()[k] for c in clients)  # noqa: E731
        res = {"driver": self.driver, "model": self.a.model, "app": self.a.server_name, "run_dir": self.run_dir, "wall_s": round(wall, 2),
               "cache": bool(self.a.cache), "claude_turns": turns, "claude_s": round(tot("seconds"), 2),
               "input_tokens": tot("input_tokens"), "output_tokens": tot("output_tokens"),
               "uncached_input_tokens": tot("uncached_input_tokens"), "cache_write_tokens": tot("cache_write_tokens"),
               "cache_read_tokens": tot("cache_read_tokens"), "input_equiv_tokens": tot("input_equiv_tokens"),
               "per_model": per_model, "small_model": self.a.small_model if small else None,
               "big_input_tokens": claude.totals()["input_tokens"], "big_input_equiv_tokens": claude.totals()["input_equiv_tokens"],
               "big_output_tokens": claude.out_tokens, "big_turns": claude.calls,
               "tool_calls": self.tool_calls, "tool_s": round(self.tool_time, 2),
               "jev_calls": self.jev_calls, "jev_errors": self.jev_errors, "jev_commits": self.jev_commits,
               "jev_declined": self.jev_declined, "jev_s": round(self.jev_time, 2), "jev_cost_usd": round(self.jev_cost, 6),
               "threshold": self.a.threshold,
               "pages_fetched": pages, "pages_named": named, "answer_chars": len(answer)}
        json.dump(res, open(os.path.join(self.run_dir, "result.json"), "w"), indent=2)
        if self.on_event:
            self.on_event({"kind": "done", "t": round(wall, 3), "result": res, "answer": answer})
        return res




def server_from_mcp_json(path, name):
    cfg = json.load(open(path))
    servers = cfg.get("mcpServers") or cfg
    if name not in servers:
        sys.exit("no server %r in %s (have: %s)" % (name, path, ", ".join(sorted(servers))))
    s = servers[name]
    if "command" not in s:
        sys.exit("server %r is not a stdio server (no command); the agent needs a local MCP server" % name)
    cmd = [s["command"]] + list(s.get("args") or [])
    if "mcp_proxy.py" in " ".join(cmd) and "--" in cmd:
        cmd = cmd[cmd.index("--") + 1:]   # unwrap a Jevsight-proxied entry: talk to the real server
    return cmd, dict(s.get("env") or {})


def main():
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", help="the research task (read-only)")
    ap.add_argument("--task-file", help="read the task from a file")
    ap.add_argument("--mcp-json", help="an .mcp.json to take the server from")
    ap.add_argument("--name", help="server name in --mcp-json")
    ap.add_argument("--server", help='stdio MCP server command, e.g. "uvx mcp-server-fetch"')
    ap.add_argument("--read-only", default="", help="extra tool names Jev may call, comma-separated")
    ap.add_argument("--strict", action="store_true", help="only readOnlyHint tools and --read-only names; no name rule")
    ap.add_argument("--driver", choices=["llm", "jev"], default="jev", help="jev: Jev takes routine turns; llm: Claude decides every call")
    ap.add_argument("--model", default=os.environ.get("JEVSIGHT_MODEL") or os.environ.get("CLAUDE_PLUGIN_OPTION_MODEL") or "claude-opus-5-5")
    ap.add_argument("--threshold", type=float, default=float(os.environ.get("JEVSIGHT_THRESHOLD") or os.environ.get("CLAUDE_PLUGIN_OPTION_THRESHOLD") or 0.4))
    ap.add_argument("--max-chain", type=int, default=12)
    ap.add_argument("--max-turns", type=int, default=40)
    ap.add_argument("--no-cache", dest="cache", action="store_false", help="disable prompt caching")
    ap.add_argument("--out", help="run directory (default ~/jevsight-races/agent-<stamp>-<driver>)")
    ap.add_argument("--quiet", action="store_true", help="print only the answer and the summary line")
    a = ap.parse_args()
    if a.task_file:
        a.task = open(a.task_file).read()
    if not a.task or not a.task.strip():
        sys.exit("give the task with --task or --task-file")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set (put it in the environment or ./.env)")
    if a.mcp_json and a.name:
        a.server_cmd, a.server_env = server_from_mcp_json(a.mcp_json, a.name)
        a.server_name = a.name
    elif a.server:
        a.server_cmd, a.server_env = shlex.split(a.server), {}
        a.server_name = os.path.basename(a.server_cmd[-1] if len(a.server_cmd) > 1 else a.server_cmd[0])
    else:
        sys.exit('give the server with --mcp-json PATH --name NAME, or --server "command"')
    a.infer_read_only = not a.strict
    a.small_model = None
    a.small_max_tokens = 1024
    a.prompt = a.task
    run_dir = a.out or os.path.join(os.path.expanduser(os.environ.get("JEVSIGHT_RUNS_DIR", "~/jevsight-races")),
                                    "agent-%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), a.driver))
    real_stdout = sys.stdout
    if a.quiet:
        sys.stdout = open(os.devnull, "w")
    try:
        res = Run(a, a.driver, run_dir).run()
    finally:
        sys.stdout = real_stdout
    print(open(os.path.join(run_dir, "answer.md")).read())
    print("\n---")
    print("Jevsight agent: %.1fs, %d model turns, %d tool calls (Jev made %d, declined %d, errors %d), %s input tokens%s; run dir %s" % (
        res["wall_s"], res["claude_turns"], res["tool_calls"], res["jev_commits"], res["jev_declined"], res["jev_errors"],
        "{:,}".format(res["input_tokens"]), (" (%s billed-equivalent)" % "{:,}".format(res["input_equiv_tokens"])) if res.get("cache") else "",
        run_dir))


if __name__ == "__main__":
    main()

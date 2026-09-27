"""Predict Claude's next shell command.

JevPredictor asks Jev (TypeSafe's System One model) two Choice questions in one
request: what kind of action comes next, and which candidate command. Jev returns
a full probability map for each, so P(command c) = P(run_command) * P(c).

HeuristicPredictor is a stand-in used only when no API key is set, so the rest
of the pipeline can be tested. Events record which predictor produced each guess.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import queue
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from common import KEY_ENV, api_key, opt, provider

ACTIONS = {
    "run_command": "runs a shell command such as tests, a type check, a search or git",
    "edit_file": "edits or creates a file",
    "read_file": "reads or searches files with a built-in tool, not the shell",
    "finish": "stops using tools and replies to the user",
}

ENDPOINTS = {
    "openrouter": ("https://openrouter.ai/api/v1/systemone", "typesafe/jev-1.13"),
    "typesafe": ("https://api.typesafe.ai/v1/systemone", "jev-latest"),
    "vercel": ("https://ai-gateway.vercel.sh/v1/evaluate", "typesafe-ai/jev"),
}


MAX_TRACE_CHARS = 24000

_SSL_CTX = None


def ssl_context():
    """Default TLS context; if it has no CA certificates (python.org builds on macOS before
    'Install Certificates.command' is run), fall back to certifi's bundle when it is installed."""
    global _SSL_CTX
    if _SSL_CTX is None:
        ctx = ssl.create_default_context()
        try:
            empty = ctx.cert_store_stats().get("x509_ca", 0) == 0
        except Exception:
            empty = False
        if empty:
            try:
                import certifi
                ctx = ssl.create_default_context(cafile=certifi.where())
            except ImportError:
                pass
        _SSL_CTX = ctx
    return _SSL_CTX


def render_state(prompt: str, steps: list, facts: dict, sections=None) -> str:
    """Full trace of every tool call so far (oldest first), trimmed from the front only if huge.
    `sections` are extra (title, lines) blocks shown before the trace, e.g. an MCP server's tool list.
    Steps starting with `Claude says:` are Claude's own narration between calls (see narration.py)."""
    from narration import n_tool_steps
    trace = ["%d. %s" % (i, st) for i, st in enumerate(steps, 1)]
    while trace and sum(len(t) + 1 for t in trace) > MAX_TRACE_CHARS:
        trace.pop(0)
    lines = ["TASK GIVEN TO THE CODING AGENT:", (prompt or "(unknown)")[:1500], ""]
    for title, body in (sections or []):
        lines.append(title)
        lines.extend(body if isinstance(body, list) else [str(body)])
        lines.append("")
    lines.append("EVERY TOOL CALL SO FAR (oldest first, %d calls). Lines starting with `Claude says:` are the "
                 "agent's own words between calls; the last one is what it says it is about to do:" % n_tool_steps(steps))
    if len(trace) < len(steps):
        lines.append("(%d earlier lines omitted)" % (len(steps) - len(trace)))
    lines.extend(trace)
    lines.append("")
    lines.append("FACTS:")
    for k, v in facts.items():
        lines.append("- %s: %s" % (k, v))
    return "\n".join(lines)


class PredictionError(Exception):
    def __init__(self, msg, retryable=False):
        super().__init__(msg)
        self.retryable = retryable


class Route:
    """One way to reach Jev (a provider + key), with kept-alive HTTPS connections and its own health."""

    def __init__(self, name, key, timeout, primary=False):
        url, model = ENDPOINTS[name]
        if primary and opt("base_url"):
            url = opt("base_url")
        self.name, self.key, self.timeout = name, key, timeout
        self.url = url
        self.model = (opt("model") if primary else None) or model
        u = urllib.parse.urlsplit(url)
        self.host, self.path = u.netloc, (u.path or "/") + (("?" + u.query) if u.query else "")
        self.pool = queue.LifoQueue(maxsize=4)
        self.fail_streak = 0
        self.cooldown_until = 0.0
        self.last_error = None
        self.use_urllib = bool(os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"))

    def body(self, state, candidates, actions=None, action_instr=None, choice_instr=None):
        body = {
            "model": self.model,
            "state": state,
            "questions": {
                "next_action": {
                    "type": "choice",
                    "instructions": action_instr or "Given the coding agent's task and every step so far, what kind of action will it take next?",
                    "criteria": actions or ACTIONS,
                },
                "command": {
                    "type": "choice",
                    "instructions": choice_instr or "If the agent's next action is running a shell command, which exact command will it run?",
                    "criteria": {c: c for c in candidates[:254]},
                },
            },
        }
        order = [x.strip() for x in (opt("gateway_order", "digitalocean,typesafe-ai") or "").split(",") if x.strip()]
        if self.name == "vercel" and order:
            body["providerOptions"] = {"gateway": {"order": order}}
        return body

    def _conn(self):
        try:
            return self.pool.get_nowait()
        except queue.Empty:
            return http.client.HTTPSConnection(self.host, timeout=self.timeout, context=ssl_context())

    def post(self, body):
        data = json.dumps(body).encode()
        headers = {"Authorization": "Bearer %s" % self.key, "Content-Type": "application/json"}
        if self.use_urllib:
            req = urllib.request.Request(self.url, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout, context=ssl_context()) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as e:
                raise PredictionError("%s HTTP %s: %s" % (self.name, e.code, e.read().decode(errors="replace")[:200]),
                                      retryable=e.code == 429 or e.code >= 500)
            except (urllib.error.URLError, OSError) as e:
                raise PredictionError("%s: %s" % (self.name, e), retryable=True)
        conn = self._conn()
        try:
            conn.request("POST", self.path, body=data, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
        except (http.client.HTTPException, OSError) as e:
            conn.close()
            raise PredictionError("%s: %s" % (self.name, e), retryable=True)
        try:
            self.pool.put_nowait(conn)  # keep the connection alive for the next call
        except queue.Full:
            conn.close()
        if resp.status >= 400:
            raise PredictionError("%s HTTP %s: %s" % (self.name, resp.status, raw.decode(errors="replace")[:200]),
                                  retryable=resp.status == 429 or resp.status >= 500)
        try:
            return json.loads(raw.decode())
        except ValueError as e:
            raise PredictionError("%s: bad JSON: %s" % (self.name, e))


def route_key(name):
    """A route only ever uses its own provider's key (never another provider's)."""
    own = (os.environ.get(KEY_ENV[name]) or "").strip()
    if own:
        return own
    explicit = (opt("api_key") or "").strip()  # plugin setting: belongs to the chosen provider only
    return explicit if explicit and name == provider() else None


class JevPredictor:
    """Calls Jev over every configured route (Vercel, OpenRouter, TypeSafe), failing over on overload."""

    name = "jev"

    def __init__(self):
        timeout = float(opt("timeout", "4") or 4)
        self.retry_budget = float(opt("retry_budget", "2.5") or 2.5)
        self.cooldown_s = float(opt("cooldown", "5") or 5)
        primary = provider()
        order = [primary] + [n for n in ("vercel", "openrouter", "typesafe") if n != primary]
        self.routes = []
        for n in order:
            key = route_key(n)
            if key:
                self.routes.append(Route(n, key, timeout, primary=(n == primary)))
        first = self.routes[0] if self.routes else Route(primary, None, timeout, primary=True)
        self.provider, self.url, self.model, self.key = first.name, first.url, first.model, first.key
        self.cache = {}

    def request_body(self, state: str, candidates: list) -> dict:
        return (self.routes[0] if self.routes else Route(provider(), None, 4, primary=True)).body(state, candidates)

    def call(self, body: dict) -> dict:
        """Raw call on the first route (used by doctor.py)."""
        return self.routes[0].post(body)

    def call_any(self, state, candidates, **qopts) -> dict:
        key = hashlib.sha1((state + "\x00" + "\x00".join(candidates) + json.dumps(qopts, sort_keys=True)).encode()).hexdigest()
        hit = self.cache.get(key)
        if hit and time.time() - hit[0] < 120:
            return hit[1]
        deadline = time.time() + self.retry_budget
        delay, last = 0.2, next((r.last_error for r in self.routes if r.last_error), None)
        while True:
            live = [r for r in self.routes if time.time() >= r.cooldown_until]
            if not live:
                soonest = min(r.cooldown_until for r in self.routes) - time.time()
                why = (" last error: %s" % str(last)[:120]) if last else ""
                raise PredictionError("all Jev routes cooling down after upstream errors (%.0fs left)%s" % (soonest, why))
            for r in live:
                try:
                    out = r.post(r.body(state, candidates, **qopts))
                    r.fail_streak = 0
                    out["_route"] = r.name
                    self.cache[key] = (time.time(), out)
                    if len(self.cache) > 128:
                        self.cache.pop(next(iter(self.cache)))
                    return out
                except PredictionError as e:
                    last = r.last_error = e
                    r.fail_streak += 1
                    if r.fail_streak >= 3:
                        r.cooldown_until = time.time() + self.cooldown_s
                    if not e.retryable:
                        raise
            if time.time() + delay > deadline:
                raise last or PredictionError("no Jev route answered")
            time.sleep(delay)
            delay *= 2

    @staticmethod
    def _probs(answers: dict, qid: str) -> dict:
        a = answers.get(qid) or {}
        p = a.get("probabilities") or a.get("distribution") or {}
        if isinstance(p, list):  # tolerate [{"option":..,"probability":..}]
            p = {d.get("option") or d.get("label"): d.get("probability", 0) for d in p if isinstance(d, dict)}
        if not p and a.get("choice") is not None:
            p = {a["choice"]: float(a.get("confidence", 1.0))}
        return {k: float(v) for k, v in p.items() if k is not None}

    def predict(self, state: str, candidates: list) -> dict:
        if not self.routes:
            raise PredictionError("no API key")
        resp = self.call_any(state, candidates)
        answers = resp.get("answers") or resp.get("data", {}).get("answers") or {}
        actions = self._probs(answers, "next_action")
        cmds = self._probs(answers, "command")
        p_run = actions.get("run_command", 0.0)
        return {"p_run": p_run, "actions": actions, "route": resp.get("_route"),
                "commands": {c: p_run * cmds.get(c, 0.0) for c in candidates}}


def _generic(self, state, actions, target, candidates, action_instr, choice_instr):
    resp = self.call_any(state, candidates, actions=actions, action_instr=action_instr, choice_instr=choice_instr)
    answers = resp.get("answers") or {}
    acts = self._probs(answers, "next_action")
    cm = self._probs(answers, "command")
    p_t = acts.get(target, 0.0)
    gw = (resp.get("providerMetadata") or {}).get("gateway") or {}
    return {"p_run": p_t, "actions": acts, "route": resp.get("_route"), "usage": resp.get("usage"),
            "cost_usd": float(gw["cost"]) if gw.get("cost") not in (None, "") else None,
            "commands": {c: p_t * cm.get(c, 0.0) for c in candidates}}


JevPredictor.predict_generic = _generic


class HeuristicPredictor:
    """Stand-in predictor for tests: after an edit, the agent usually re-runs its last check."""

    name = "heuristic"

    def predict(self, state: str, candidates: list) -> dict:
        after_edit = "last_action: edit_file" in state
        p_run = 0.7 if after_edit else 0.35
        weights = {}
        for i, c in enumerate(candidates):
            weights[c] = 1.0 / (i + 1) ** 1.5
        total = sum(weights.values()) or 1.0
        return {
            "p_run": p_run,
            "actions": {"run_command": p_run},
            "commands": {c: p_run * w / total for c, w in weights.items()},
        }


def _heuristic_generic(self, state, actions, target, candidates, action_instr=None, choice_instr=None):
    """Stand-in for MCP: trusts the candidate order (the proxy ranks calls that use the newest ids
    first). Sharp enough (~0.43 on the top choice) that the EV gate launches one guess per step."""
    p_t = 0.7
    w = {c: 1.0 / (i + 1) ** 2 for i, c in enumerate(candidates)}
    tot = sum(w.values()) or 1.0
    return {"p_run": p_t, "actions": {target: p_t}, "commands": {c: p_t * v / tot for c, v in w.items()}}


HeuristicPredictor.predict_generic = _heuristic_generic


def make_predictor():
    forced = (opt("predictor") or "").lower()
    if forced == "heuristic" or (not api_key() and forced != "jev"):
        return HeuristicPredictor()
    return JevPredictor()

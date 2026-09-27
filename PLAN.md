# PLAN.md: finish the Jevsight MCP proxy + Neon race

This file is for Claude Code running in this repo. Work top to bottom. Tick boxes as you go.
Deadline: submission is due **Sun Sep 27, 11:00 AM CT** (5 min demo video + repo link).

## Status (updated 2026-09-26 by Claude Code)

2026-09-26 later: Jev's state now carries Claude's narration between calls (feed from the stream in races, transcript
tail in plugin use), the MCP server's tool catalog, and the newest three results at full length. See README "What Jev sees".
Replay on two Neon baselines: top-1 0.60 -> 0.80, ECE ~0.33 -> 0.18. Not yet raced live: the shell (hooks) path with
narration, only smoke-tested with fake hook events.

Steps 2, 3, 4 and 5 are implemented and rehearsed offline (`tests/test_mcp_proxy.py` passes; `race.py --app neon` runs end to end
against `tests/fake_mcp_server.py` with `tests/fake_claude.py`). Waiting on the user for: the step-1 ceiling probe, `NEON_API_KEY`
in `.env` for the smoke test and the live race, and the demo. Found and fixed on the way: this machine's python.org Python 3.13
had no CA certificates, so every live Jev call failed TLS verification (predictor.py now falls back to certifi).

## Update 2026-09-26 03:40: slower MCP servers

The Neon ceiling came in at 6.9% (`race-20260926-011950-1`), under the 10% gate. Two more MCP apps were added so the race can
target slower tools: `--app github` (official github-mcp-server v1.12.2 in `--read-only` mode, token from `gh auth token`,
0.3-0.7s calls with multi-second spikes) and `--app fetch` (`uvx mcp-server-fetch`, 0.6-1.7s per page, walks the asyncio docs).
The proxy learned enums, integer ids, `full_name` splitting, numeric JSON values, markdown links, the fetch server's
`start_index` hint, `JEVSIGHT_READ_ONLY`, and seeds candidates from links named in the task. Scripted chains through the proxy
(stand-in predictor) hit every `start_index` continuation on fetch. Live races with Jev are still the user's to run.

## 0. Context (read first)

**What Jevsight is.** A Claude Code plugin. After each tool result, TypeSafe's Jev (a calibrated classifier) predicts the agent's next tool call. If the expected value is positive, the harness runs that call early. When Claude asks for it, the saved result is served at once.

    EV = p * min(call_time, think_time) - (1 - p) * alpha * call_time      (alpha 0.25, max 2 launches)

**Why we are pivoting to MCP.** On coding tasks the ceiling is tiny. Claude batches its edits and runs the check 0s after, so there is no idle gap to hide work in. The perfect-predictor ceiling was 0.6 to 4% of wall time (see `~/jevsight-races/race-20260926-000107-1`). MCP data exploration looks different: calls are sequential, network-bound, and each call needs IDs from the last result. Claude Code hooks cannot replace an MCP result, so Jevsight sits as a **stdio MCP proxy** between Claude and the real server.

**What already exists.**
- `plugins/jevsight/bin/mcp_proxy.py`: written, compiles, **never run**. Run it as `python3 mcp_proxy.py -- <upstream server cmd...>`. What it does:
  - Relays JSON-RPC line by line.
  - Learns tools from `tools/list`.
  - Builds candidate calls (tool x argument values) from IDs seen in earlier results.
  - Asks `predictor.predict_generic(...)` for the next call.
  - Launches read-only calls upstream with ids `jevsight-<hex>`.
  - Serves hits from the saved response.
  - Invalidates all saved results on any non-read-only call.
  - Logs to `$JEVSIGHT_DATA/events.jsonl` with the same event types as the Bash daemon: `predict`, `launch`, `hit`, `miss`, `saved`, `wasted`, `job_done`, `outcome`, `predict_error`.
- `plugins/jevsight/bin/predictor.py`: has `predict_generic(state, actions, target, candidates, action_instr, choice_instr)` on both `JevPredictor` and `HeuristicPredictor`. Returns `{"p_run", "actions", "route", "commands": {candidate: p}}`.
- `eval/mcp_probe.py`: runs one plain Claude session on a read-only Neon task using the user's personal config (server named `Neon`). It prints the perfect-predictor ceiling for MCP calls.
- `race/race.py`: side-by-side race rig. It is currently Bash/npm specific (see step 3).
- `eval/bench.py`, `eval/replay_bench.py`: live-race and offline-replay evals. Both are Bash specific.

**Neon MCP facts.**
- Command: `npx -y @neondatabase/mcp-server-neon start <NEON_API_KEY>` (v0.6.5).
- It publishes no `readOnlyHint`.
- Read-only tools: `list_projects`, `list_shared_projects`, `list_organizations`, `describe_project`, `describe_branch`, `get_database_tables`, `describe_table_schema`, `list_branch_computes`, `list_slow_queries`.
- Params: `projectId`, `branchId`, `databaseName`, `tableName`, `computeId`.

## Hard rules

1. **Never speculate** anything that writes, costs money, or returns secrets. That covers `run_sql`, `run_sql_transaction`, `get_connection_string`, `create_*`, `delete_*`, `reset_*`, `provision_*`, migrations and tuning. Keep the `NEVER` regex in `mcp_proxy.py`.
2. All Neon work is **read-only** against the user's real account. The race prompt must say so.
3. **Never write, print or log API keys.** The user edits `.env` himself. Keys used: `AI_GATEWAY_API_KEY`, optional `OPENROUTER_API_KEY`, `NEON_API_KEY`. Each Jev route only ever sends its own provider's key (`route_key` in predictor.py). Don't break that.
4. **Never fabricate results.** Every number in the README or the demo must come from a real race or replay directory. If the heuristic stand-in was used, label it `HEURISTIC STAND-IN`, never Jev.
5. Races use the clean config `CLAUDE_CONFIG_DIR=~/.jevsight-claude`. That keeps the user's personal hooks and MCP servers out. For MCP races, also pass `--strict-mcp-config` so only the race's `--mcp-config` servers load.
6. Correctness must never depend on Jev. If Jev is slow, overloaded (429/503 are common) or down, the proxy just relays.
7. The user runs long jobs (races, probes) in his own terminal. Give him the exact command. Don't loop on retries.

## 1. Gate: measure the MCP ceiling (5 min, user runs it)

- [ ] (user runs) Ask the user to run `python3 eval/mcp_probe.py` and paste the `Perfect-predictor ceiling` line.
- **If the ceiling is 10% of wall time or more:** continue with this plan.
- **If it is under 10%:** Claude probably parallelized the calls in one turn. Check `ceiling.md` for calls with ~0s idle. Then:
  - Try a prompt that forces the dependency chain, e.g. "for each table, decide from its schema which table to inspect next". Re-probe once.
  - If it is still low, stop and tell the user. The honest story becomes "we measured where speculation can and can't help". Use the numbers we have.

## 2. Make the proxy work (test with fakes, no network, no Jev)

- [x] **2a. Fake MCP server** at `tests/fake_mcp_server.py`. Stdio, newline-delimited JSON-RPC.
  - Handles `initialize`, `notifications/initialized`, `tools/list` and `tools/call`.
  - Exposes Neon-shaped tools with the same names and required params. Include one write tool, `create_branch`.
  - `list_projects` returns text JSON with `{"id":"proud-sun-123456", ...}`.
  - `describe_project` returns `"default_branch_id":"br-cool-9"`.
  - `get_database_tables` returns `"table_name"` entries: `users`, `orders`, `items`.
  - `describe_table_schema` returns columns.
  - Every call sleeps a configurable `FAKE_DELAY` (default 1.0s) and counts calls per key in a stats file, so the test can check what ran upstream.
- [x] **2b. Scripted client** at `tests/test_mcp_proxy.py`, plain `python3`, no pytest needed.
  - Spawn: `python3 plugins/jevsight/bin/mcp_proxy.py -- python3 tests/fake_mcp_server.py`.
  - Env: `JEVSIGHT_PREDICTOR=heuristic JEVSIGHT_MODE=on JEVSIGHT_DATA=<tmp>`.
  - Script: `initialize` → `tools/list` → `list_projects` → sleep 2s → `describe_project{projectId}` → sleep 2s → `get_database_tables{...}` → sleep 2s → `describe_table_schema{...}` → `create_branch` → one more read.
  - Assert every response has the right `id` and a result equal to a direct call.
  - Assert at least one `hit` in events.jsonl, with the hit call's client-side latency well under `FAKE_DELAY`.
  - Assert `create_branch` was **never** sent upstream more than once, i.e. never speculated.
  - Assert that after `create_branch`, a saved result from before it is not served (a `wasted` event with reason `stale:write:create_branch`).
  - Assert no `jevsight-*` id ever reaches the client.
  - Assert `JEVSIGHT_MODE=off` gives a pure passthrough.
  - `JEVSIGHT_PREDICTOR=heuristic` already forces the stand-in (`make_predictor` reads `opt("predictor")`).
- [x] **2c. Fix known gaps in `mcp_proxy.py`**, found by reading. Confirm each with the test:
  - **Wrapped args.** Neon may nest arguments under `params` (`{"params": {"projectId": ...}}`). `on_client_call` only records top-level string args into `used_args`, and `candidates()` then builds `extra` from top-level keys. Flatten one level of `params` when recording and when building extras.
  - **Argument canonicalization.** Claude may add optional args with default values, e.g. `databaseName: "neondb"` or `branchId` equal to the default branch. The exact-key match then misses. In `call_key`, drop args whose value equals the schema `default`. Also add a small alias match: treat a call missing `branchId` as equal to one with the project's default branch only if the schema says it's optional. Keep it conservative. A wrong hit is worse than a miss.
  - Use `asyncio.get_running_loop()` instead of `get_event_loop()` in `Job` and `run_in_executor`.
  - If Claude sends `notifications/cancelled` for a request that is being served from a job, drop the reply cleanly.
  - `run_sql` with a plain `SELECT` currently invalidates everything. That's fine for now; leave a comment. Optional: don't invalidate for `run_sql` whose `sql` matches `^\s*(select|with|explain|show)\b`, but still never speculate it.
  - When upstream exits, flush pending replies as JSON-RPC errors before `os._exit`.
  - Upstream stderr goes to our stderr. Make sure nothing but JSON-RPC ever goes to stdout: no prints, and no log lines to stdout.
- [~] **2d. Real Neon smoke test.** (`tests/neon_smoke.py` written; run it once `NEON_API_KEY` is in `.env`) It needs `NEON_API_KEY` in `.env`, which the user adds. Send `initialize`, `tools/list` and `list_projects` through the proxy with the real server. Print the tool names and whether args are wrapped in `params`. Update `READ_ONLY` and `PARAM_SOURCES`/`VALUE_FILTERS` if the real IDs or keys differ, e.g. check that project ids really match `^[a-z]+-[a-z]+-[a-z0-9]+$`. Don't print the key or connection strings.

## 3. Neon race in `race/race.py`

- [x] Add app `"neon"` to `APPS`. There is no starter dir, so make `prepare()` app-aware: for `neon`, create an empty workdir. No copy, no npm install, no git init needed.
- [x] **Prompt.** Read-only, forces a dependency chain, same for both sides. Start from `DEFAULT_PROMPT` in `eval/mcp_probe.py`, or the variant that won the ceiling gate in step 1. Tell Claude the answer must be a markdown report.
- [x] **Per-side MCP config.** Write it to `<run_dir>/<side>.mcp.json`:
  - baseline: `{"mcpServers":{"neon":{"command":"npx","args":["-y","@neondatabase/mcp-server-neon","start","<KEY>"]}}}`
  - jevsight: `{"mcpServers":{"neon":{"command":"python3","args":["<ROOT>/plugins/jevsight/bin/mcp_proxy.py","--","npx","-y","@neondatabase/mcp-server-neon","start","<KEY>"],"env":{"JEVSIGHT_MODE":"on","JEVSIGHT_DATA":"<run_dir>/jevsight-data","JEVSIGHT_TASK":"<prompt>","AI_GATEWAY_API_KEY":"...","OPENROUTER_API_KEY":"..."}}}}`
  - Only include keys that are set.
  - These files contain secrets. Write them with mode 0600 and **delete them when the race ends**, in a `finally`.
  - First check whether the Neon server can read the key from an env var instead of argv. If it can, prefer the env var and keep the key out of argv.
- [x] **Side.run tool flags.** Take these from the app instead of hardcoding:
  - neon: `--allowedTools mcp__neon`
  - `--disallowedTools "Bash Edit Write Agent Task WebFetch WebSearch"`
  - `--mcp-config <file> --strict-mcp-config`
  - No `--plugin-dir`
  - No `--permission-mode acceptEdits` needed. Keep `-p` and stream-json.
- [x] **Wait tracking.** In `Side.on_event`, treat tool names starting with `mcp__` like Bash:
  - Record the call time.
  - Show `mcp tool_name {args}` with `...running`, then replace it with the wait. Green if under 1s on the jevsight side.
  - Add `mcp_calls` and `mcp_wait` to the record and scoreboard. Keep `bash_wait` for the other apps.
- [x] **Verify.** For neon there is no npm check. Save each side's final `result` text to `<run_dir>/<side>.answer.md`. Mark `check_passed` true if the run finished without error and the answer names at least one table. Also record whether both sides listed the same set of tables, as a crude equivalence check.
- [x] **Header.** It must say `Jev` or `HEURISTIC STAND-IN`. It is Jev only if a Jev key is set. Also show the live Jev failure rate from `predict_error` events, since overload is real.
- [x] Run a dry pass with `--app neon --no-ui --only jevsight` using the fake server. Add a hidden `--neon-cmd` override so the race can point at `tests/fake_mcp_server.py` without a Neon key. Use it for a no-network rehearsal.

## 4. Evals

- [x] **`eval/bench.py`**
  - Generalize `side_stats` wait tracking to `mcp__*` tools. For MCP, the canonical key is `name + sorted-JSON args`, with the same canonicalization as `call_key`.
  - Report MCP wait as a share of wall time.
  - Hits and saved seconds come from events.jsonl, same as now.
- [x] **`eval/replay_bench.py`**
  - Add an MCP mode: rebuild the baseline trajectory of `mcp__neon__*` calls from `baseline.stream.jsonl` + `baseline.times.jsonl`.
  - At each step, rebuild the candidate list with the **same code as the proxy**. Factor `Proxy.candidates`/`param_values` into a pure function in `mcp_proxy.py` that takes `(tools, read_only, values, used_args)`, and import it here.
  - Ask Jev with patient retries and cache the answers in `<race>/replay_cache.json`.
  - Simulate the policies already there: never, top-1, p>0.5, EV alpha, perfect ceiling.
  - This makes the result immune to Jev rate limits during the live race.
- [x] **Calibration.** Report ECE and a reliability table for MCP predictions too. Coding runs showed Jev is overconfident (ECE ~0.45 to 0.56).
  - Optional: fit a per-session temperature on the replay, e.g. Platt scaling on held-out steps, and report EV-policy results with and without it.
  - Present that as a finding, not a hidden fix.

## 5. Ship

- [x] **README**
  - Add an "MCP servers" section. Show how to wrap any stdio MCP server in `.mcp.json`:
    `"command":"python3","args":["<path>/plugins/jevsight/bin/mcp_proxy.py","--", <original command...>]`
  - Note the read-only allowlist and that `readOnlyHint` tools are auto-allowed.
  - Add the Neon race to Quick start: `python3 race/race.py --app neon`.
- [x] **Optional helper:** `plugins/jevsight/bin/wrap_mcp.py <project>/.mcp.json`.
  - Rewrites each stdio server entry to go through the proxy, with a `.bak` backup and a `--undo` flag.
  - Never touches remote (http/sse) servers.
- [~] **Benchmarks section.** (coding numbers in; MCP/Neon rows say 'pending' until the probe and race run) Only real numbers, each with its race dir name:
  - coding ceiling (0.6 to 4%)
  - MCP ceiling from the probe
  - live Neon race result
  - replay result
- [x] Bump `plugins/jevsight/.claude-plugin/plugin.json` version to 0.2.0.
- [x] Remove the unused `HUB_STUB` from race.py.
- [x] `python3 -m py_compile` on every file, then run `tests/test_mcp_proxy.py`. It must pass.
- [ ] (not a git repo: nothing committed) If this folder is a git repo, commit in small steps with clear messages. Don't push unless the user asks.

## 6. Demo video (5 min, from real runs only)

1. **Problem (30s).** Agents sit idle while slow tools run. Coding agents batch their calls, so the ceiling there is tiny. We measured it.
2. **Idea (45s).** Jev predicts the next MCP call from the full trace. The EV gate decides whether to run it early. The proxy serves the hit. Writes and secrets are never touched.
3. **Race (2 min).** `race.py --app neon`, split screen, real Neon account. Green sub-second waits on the jevsight side. Scoreboard at the end.
4. **Holds up when pieces fail (Track 2) (45s).** Show a run where Jev returns 429/503. The jevsight side still finishes with the same answer, it just relays. Show the `predict_error` count.
5. **Numbers + install (1 min).** Replay-bench table, calibration note, then `/plugin install jevsight@jevsight` and the one-line `.mcp.json` wrap.

Record the terminal. If a live race goes badly, use a real earlier run and say which one it is. Don't stage results.

## Commands the user will run

```bash
# once
echo 'NEON_API_KEY=' >> .env         # then paste the key in an editor, not in chat
CLAUDE_CONFIG_DIR=~/.jevsight-claude claude     # /login, then quit (if not done yet)

python3 eval/mcp_probe.py                        # step 1 gate
python3 tests/test_mcp_proxy.py                  # step 2
python3 race/race.py --app neon --repeat 3       # step 3
python3 eval/bench.py ~/jevsight-races/race-*    # step 4
python3 eval/replay_bench.py ~/jevsight-races/race-XXXX
```

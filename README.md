# Jevsight

An agent loop where a calibrated classifier takes the routine tool calls and the frontier model keeps the thinking.

After every tool result, Jev (TypeSafe's System One model) is asked one multiple-choice question: *which of these exact
read-only calls comes next, or is the agent done?* When its top answer clears a threshold, the loop makes that call
itself and writes it into the transcript as if the model had asked for it. The frontier model (Claude Opus) is only
called when Jev is unsure, when the work is done, or when the next step is not a choice from a list. Same tool calls,
same answer, about half the model turns.

Measured on a seven-page documentation task with `claude-opus-5-5`, prompt caching on, medians of three:

| | wall | model turns | billed-equivalent input tokens | sources named |
| --- | --- | --- | --- | --- |
| Claude alone | 83.3s | 10 | 84.0k | 7 / 7 |
| Claude + Jev | 70.3s | 4 | 68.4k | 7 / 7 |
| Haiku navigates, Opus writes (the obvious alternative) | 109.9s | 32 | 72k Opus + 127k Haiku | 7 / 7 |

And on a 14-page reading list (one pair, cached): Claude alone 125.6s, 19 turns, 281.7k billed-equivalent; Claude + Jev
109.8s, 10 turns, 244.9k, with Jev taking 9 turns, declining 9 and getting none wrong. Both named all 14 sources
(`loop-20260926-203542-llm`, `loop-20260926-205230-jev`).

Every number in this README names the run directory it comes from; nothing is staged.

## The agent and its UI

```bash
cp .env.example .env            # add ANTHROPIC_API_KEY and a Jev key (AI_GATEWAY_API_KEY or OPENROUTER_API_KEY); edit it yourself
python3 agent/ui.py             # API on http://127.0.0.1:8765 (standard library)
cd web && npm install && npm run dev   # UI on http://localhost:3000
```

The page shows every turn as it happens: neutral cards for the model's turns, orange cards for Jev's decisions with a
probability bar per candidate and the commit threshold marked, tool rows with timings, a ticking scoreboard (wall,
model turns, tool calls, tokens, Jev cost) and the answer with the sources it named. The default mode, **Claude Code vs Claude + Jev**, starts a real Claude Code
session (the CLI, clean config, same model and MCP server) on the left and the agent on the right at the same moment;
the other modes run Claude alone, Claude + Jev, both, or the Haiku cascade. Replay plays any saved run back on the same
timeline (`/?replay=<run>,<run>&speed=4`, or `/?versus=<race-dir>,<loop-run>&speed=4` for a recorded Claude Code
session against a recorded agent run).

On the 14-page task, recorded: Claude Code 159.5s, 25 turns, 23 tool calls, $1.42; the agent 109.8s, 10 model turns, 18
tool calls of which Jev made 9 (`race-20260926-203256-1` baseline side vs `loop-20260926-205230-jev`). Different
harnesses (Claude Code has its own system prompt, tool plumbing and caching), same model, prompt, server and moment.

From the command line:

```bash
python3 agent/jevloop.py --driver both              # Claude alone, then Claude + Jev, scoreboard
python3 agent/jevloop.py --driver all --repeat 3    # plus the Haiku cascade; medians over 3
python3 agent/jevloop.py --driver both --app fetch-long   # the 14-page task
```

Runs land in `~/jevsight-races/loop-<stamp>-<driver>/` (`trace.jsonl`, `answer.md`, `result.json`) and one line per
run is appended to `~/jevsight-races/loops.jsonl`.

## How the loop decides

- **Candidates.** Every read-only tool on the MCP server × the ids in hand: values listed in the task, ids and links in
  earlier results, enum members, the arguments the model already used, and a server's own "continue from N" hint.
  Ids listed in the task are pinned for the whole run so a long reading list is never pushed out by the links on the
  pages read so far.
- **The question.** The task, every call and result so far (long results shown as head and tail with the omission
  marked), and the model's own words between calls go to Jev with two multiple-choice questions: call a tool or
  finish, and which exact call.
- **The rule.** Commit when the top candidate has p ≥ 0.4 and has not been made already (`--threshold`). On the
  seven-page task 0.4 gave 13 commits in 3 runs, every one the correct next page; 0.5 declined correct picks sitting at
  p 0.34-0.48.
- **The transcript.** A committed call is appended as an assistant `tool_use` block followed by the real `tool_result`,
  so the model can take over at any moment with nothing missing.
- **Fails soft.** Jev unsure, wrong or down: the model takes the turn as it always would. A wrong pick is one extra
  read-only page in the transcript, never a wrong answer. Nothing that writes, costs money or returns secrets is ever a
  candidate.

## Also in the repo: the Claude Code MCP proxy

The first version of this idea was a stdio proxy between Claude Code and an MCP server that runs Jev's predicted call
early and answers Claude's matching call from the saved result. It works (5 of 8 calls pre-answered on the fetch task,
tool wait cut by half) but the wait it hides is under 10% of a run, so it is no longer the product. The candidate builder
the loop uses lives in `plugins/jevsight/bin/mcp_proxy.py`; the race harness and its results below are kept for
reference.

## Reference: Claude Code races (proxy)

```bash
cd ~/Documents/jevsight
cp .env.example .env            # paste a Vercel AI Gateway key (or an OpenRouter key); NEON_API_KEY for the Neon race
python3 plugins/jevsight/bin/doctor.py   # checks the Jev call works, prints the raw answer
python3 race/race.py            # plain Claude Code vs Claude Code + Jevsight, Next.js bug fix, split screen
python3 race/race.py --app neon # same, exploring your Neon account read-only through the Neon MCP server
python3 race/race.py --app fetch  # web-fetch MCP server walking the Python asyncio docs (uvx, no key)
python3 race/race.py --app github # GitHub MCP server in --read-only mode on a public repo (gh auth login)
```

Other race options:

```bash
python3 race/race.py --repeat 5              # 5 races; results go to race/results/races.jsonl
python3 race/race.py --jevsight-mode shadow  # predict only, to measure overhead
python3 race/race.py --model <model-id>      # pin the model for both sides
python3 race/race.py --app small             # the quick TypeScript app (checks take ~4s)
python3 race/race.py --app neon --prompt "…" # your own read-only Neon task (same prompt for both sides)
```

Races run in `~/jevsight-races/` with a clean Claude Code config (`~/.jevsight-claude`, log in there once) so your personal hooks and MCP servers stay out. Each pane shows how long Claude waited on every shell command or MCP call, green when the jevsight side got it in under a second, and the race ends with a scoreboard. The header says `Jev` or `HEURISTIC STAND-IN`, and shows the live count of failed Jev calls, because overload (429/503) is real.

The Neon race is read-only against your real account: the prompt says so, the proxy never runs anything that writes, costs money or returns secrets, and `Bash`, `Edit`, `Write` and web tools are disabled for both sides. Per-side MCP configs hold the key; they are written with mode 0600 and deleted when the race ends.

## MCP servers

Wrap any stdio MCP server by putting the proxy in front of it in `.mcp.json`:

```json
{
  "mcpServers": {
    "neon": {
      "command": "python3",
      "args": ["<path>/plugins/jevsight/bin/mcp_proxy.py", "--", "npx", "-y", "@neondatabase/mcp-server-neon", "start", "<NEON_API_KEY>"],
      "env": { "JEVSIGHT_MODE": "on" }
    }
  }
}
```

Or let the helper rewrite the file (backup in `.mcp.json.bak`, `--undo` restores it; remote http/sse servers are left alone):

```bash
python3 plugins/jevsight/bin/wrap_mcp.py <project>/.mcp.json
```

What the proxy does after every tool result:

1. Builds the candidate next calls: each read-only tool × argument values taken from ids seen in earlier results (`projectId`, `branchId`, `tableName`, …), most recently discovered first.
2. Asks Jev which call comes next, and runs the top ones early when EV > 0 (at most 2 in flight). Then it keeps watching the session transcript: the moment Claude narrates its next move ("Default branch is main. Listing its tables."), it asks Jev again with those words in the state.
3. When Claude makes that call, answers from the saved result. Arguments equal to a schema default are ignored when matching, and a call without `branchId` matches one with the project's default branch (only when the schema marks `branchId` optional). Anything else is a miss and goes to the server.
4. Any call to a tool that is not read-only throws every saved result away.

Which servers speculate well: the proxy needs two things, calls that are slow relative to Claude's thinking and a next call
whose arguments are ids from earlier results (a table name, a PR number, a URL, the `start_index` a truncated page asks for).
Measured with scripted chains through the proxy on this machine (stand-in predictor, so hit counts say nothing about Jev):

| server | per call | wait share at 2.5-3s think | what the proxy predicts |
| --- | --- | --- | --- |
| Neon (`--app neon`) | 0.3s | 5-7% | next table to describe; default-branch alias |
| GitHub (`--app github`, `--read-only`) | 0.3-0.7s, spikes to 3-9s | 15-47% | PR walk: `pull_request_read` method enum × PR number, merge commit sha |
| fetch (`--app fetch`) | 0.6-1.7s | 14-23% | next page from the task's URL list; `start_index` continuation of a truncated page (3 of 3 hit, served in 0.00s) |

Read-only allowlist: `list_projects`, `list_shared_projects`, `list_organizations`, `describe_project`, `describe_branch`, `get_database_tables`, `describe_table_schema`, `list_branch_computes`, `list_slow_queries`. Tools that publish `readOnlyHint: true` are added automatically (the GitHub server does; the fetch server does not, so the fetch race passes `JEVSIGHT_READ_ONLY=fetch`). Never speculated, whatever any hint says: `run_sql`, `run_sql_transaction`, `get_connection_string`, `create_*`, `delete_*`, `reset_*`, `provision_*`, migrations and tuning.

Test it with no network and no key (fake Neon-shaped server, stand-in predictor):

```bash
python3 tests/test_mcp_proxy.py        # hits, alias hits, staleness after a write, cancel, upstream death, passthrough
python3 tests/neon_smoke.py            # real Neon server through the proxy: tool names, argument shape, id filter (needs NEON_API_KEY)
```

## Benchmarks

```bash
python3 eval/mcp_probe.py                                     # ceiling for MCP calls: one plain session, perfect-predictor bound
python3 eval/bench.py ~/jevsight-races/race-*                 # what happened live: time split, waits, hits, Jev calibration
python3 eval/replay_bench.py ~/jevsight-races/race-XXXX       # rate-limit-proof: replay the baseline run through Jev offline
```

`replay_bench.py` asks Jev what it would have predicted at every step of the recorded baseline run (retrying patiently, answers cached in the race folder), then simulates each launch policy on the real timeline. For MCP races it rebuilds the candidates with the proxy's own code from the tool schemas the proxy saved (`jevsight-data/tools.json`). Speculation never changes what Claude sees, so this measures Jevsight's effect without depending on Jev being up during the live race. It also reports calibration (ECE, reliability table) and, as a finding rather than a fix, the EV gate with a cross-fitted temperature on Jev's probabilities.

Jev routes: set both `AI_GATEWAY_API_KEY` and `OPENROUTER_API_KEY` and Jevsight fails over between them when one is overloaded.

### Results so far (real runs only; each number names its race directory)

| What | Where it comes from | Result |
| --- | --- | --- |
| Coding ceiling, Next.js one-shot | `race-20260925-222959-1`, `eval/bench.py` | perfect predictor could hide 3.1s of 374.6s wall (0.8%) |
| Coding ceiling, bug fix | `race-20260926-000107-1`, `eval/replay_bench.py` | perfect predictor 2.9s of 76.7s (3.8%); EV gate 1.8s (2.4%), 2 hits in 9 launches |
| Jev calibration on coding runs | `race-20260925-222959-1`, `race-20260926-000107-1` | overconfident: ECE 0.50 and 0.58 on P(next is a command) |
| MCP ceiling (Neon, real account) | `race-20260926-011950-1` baseline, `eval/replay_bench.py` | 5 Neon calls, 1.5s of 22.1s wall waiting on them: perfect predictor could hide 6.9% |
| Neon replay through Jev | same race, `eval/replay_bench.py` | EV gate: 3 launches, 2 hits, 0.6s saved (2.6% of wall); Jev top choice at p=0.94 was right 2 of 3 times |
| Live Neon race, Jev up | `race-20260926-011950-1` | jevsight side: 5 of 5 calls under 1s (0.34s total wait vs 1.52s baseline), 4 hits in 5 launches, 1.6s saved; wall time a dead heat (23.5s vs 23.3s) |
| Live fetch races, Jev up | `race-20260926-030003-1`, `-030324-1`, `-030429-2`, `-030845-1` | 3, 5, 5 and 5 hits out of 8 calls; jevsight waited 2.4-4.5s vs baseline 5.6-7.8s; top-1 0.29, 0.57, 0.71, 0.57; 0 Jev errors; same cheat sheet both sides. In the last race both sides made exactly 8 calls: 60.7s vs 71.6s wall |
| fetch replay through Jev | same three races, `eval/replay_bench.py` | EV gate 3.1s, 3.2s, 2.9s saved of 7.8s, 5.0s, 6.5s ceiling (wait share 7.8-8.9% of wall) |
| Live Neon races, Jev failing | `race-20260926-012015-2`, `race-20260926-012053-3` | Jev errors on 60% and 80% of calls (gateway 429/503); jevsight side still finished with the same table set as baseline |
| Narration + tool catalog in the state, replayed | `race-20260926-030942-1` and `race-20260926-011950-1` baselines, `eval/replay_bench.py` vs `--no-narration` | top-1 accuracy 0.60 -> 0.80 on both runs; top-choice ECE 0.32 -> 0.18 and 0.34 -> 0.18; on the 3 of 5 steps Claude narrated, top-1 0.33 from the result alone vs 0.67 after the narration. EV gate unchanged at 5 hits in 6 launches, 1.3s saved, since the extra hits were already served through the default-branch alias |
| Live Neon race with the narration feed | `race-20260926-030942-1` | narration reached the proxy 0.16 to 0.50s before each call; 3 hits in 4 launches, 1.7s saved, 0.2s wasted, 0 Jev errors, same table set. The narration-triggered prediction finished a few ms before the call (Jev latency 0.33 to 0.45s), too late to launch anything new on a 0.3s server; the 0.15s debounce was removed for narration afterwards. Wall time 48s vs 23s is Claude's own API latency on the baseline side, not Jevsight |

| API loop, Claude decides vs Claude + Jev, uncached | `agent/jevloop.py --driver both --no-cache`; `loop-20260926-032658/033045`, `-033612`, `-034357` | mean of 3 pairs, claude-opus-5-5: wall 89.6s vs 71.6s (-20%), 11 vs 5 model turns, 10.3 vs 7 tool calls, 263k vs 140k input tokens (-47%); Jev 3 commits / 4 declined / 0 errors every run; both answers named all 7 pages every time |
| API loop, same pair with prompt caching on | `loop-20260926-064947`, `-065417`, `-065839` (`llm` and `jev`) | mean of 3: wall 82.3s vs 76.8s (-7%), 9.7 vs 5.7 turns, 83.3k vs 76.7k billed-equivalent input tokens (-8%; cache writes at 1.25x, reads at 0.1x). Caching already removes most of the re-read cost that skipped turns were saving; the turn cut stands |
| API loop, Haiku-cascade alternative (Haiku 4.5 navigates with a navigation-only instruction, Opus 5.5 writes) | `agent/jevloop.py --driver cascade`; `loop-20260926-064355/064555/064740-cascade` uncached, `-064947/065417/065839-cascade` cached | slower than plain Opus in all 6 runs: cached mean wall 109.9s, 32 turns, 30 tool calls (Haiku paged the docs in 5,000-char slices every run), 72k Opus-equivalent + 127k Haiku-equivalent tokens vs Jev's 77k Opus-equivalent total. A first version without the navigation-only instruction (`-063545/063814/064020`) also wasted 35-42s on a Haiku write-up that was then discarded |
| API loop, Jev at commit threshold 0.4 (now the default), cached | `loop-20260926-070514`, `-070624`, `-070730` (`jev`) vs the cached `llm` runs above | median wall 70.3s vs 83.3s (-16%), 4 vs 10 model turns (-60%), 68.4k vs 84.0k billed-equivalent tokens (-19%); 13 commits in 3 runs, every one the correct next page, 0 errors, all 7 pages named. At 0.5 the same runs declined correct picks sitting at p 0.34-0.48. Repeats started within five minutes share a cached prefix (system, tools, first page), a small bias that favours every driver equally |
| API loop, 14-page task (`--app fetch-long`), cached, one pair | `loop-20260926-203542-llm` vs `loop-20260926-205230-jev` | 125.6s vs 109.8s (-13%), 19 vs 10 model turns (-47%), 281.7k vs 244.9k billed-equivalent (-13%), 18 tool calls each, all 14 pages named on both sides; Jev 9 commits / 9 declined / 0 errors, none wrong. The first Jev run on this task (`-203542-jev`) committed only 3 times: the links inside each page had pushed the task's own reading list out of the candidate window, and long results were shown to Jev as a cut-off head that hid the server's own "truncated" notice. Both fixed in the candidate builder the same evening; the replay bench (`--steps --dump-states`) is what found them |
| Jev's own cost | gateway model record for `typesafe-ai/jev`; `providerMetadata.gateway.cost` on each call | $0.042 per million input tokens, zero output, no prompt caching offered or needed; 7 calls per loop run, about a tenth of a cent per task |

Reading the fetch rows: with the page list in the task and the server's own "start_index" hint, Jev picks the next page or the continuation most of the time and the proxy serves it in under 10ms. The two misses that repeat are Claude switching `max_length` mid-run (a value no earlier call used) and the last page. Wall-time differences between sides are dominated by how many calls Claude chose to make, so compare the wait columns, not the totals.

Reading the Neon rows: the mechanism works (every call served under a second, two thirds of the launched guesses hit) but the ceiling is small because Neon answers in about 0.3s and Claude thinks for about 3s between calls. On a task like this the time is the model's, not the tools'. Speculation pays where tool calls are slow relative to thinking.

Why the coding ceiling is tiny: Claude batches its edits and issues the check 0s after the last one, so there is no idle gap to hide work in. MCP data exploration is different: calls are sequential, network-bound, and each needs ids from the previous result.

A no-network rehearsal of the Neon race (fake server with 1s calls, stand-in predictor, `tests/fake_claude.py` walking a fixed 6-call chain) served 3 of 6 calls in under 10ms and finished 19% sooner with the same answer. That is a plumbing check, not a benchmark: it says nothing about Jev.

## Install as a plugin

```bash
/plugin marketplace add PratLyZol/jevsight
/plugin install jevsight@jevsight
```

Or try it locally without a marketplace: `claude --plugin-dir ./plugins/jevsight`.

Then, in a project with a stdio MCP server in its `.mcp.json`:

```
/jevsight:agent fetch Read https://docs.python.org/3/library/asyncio.html and https://docs.python.org/3/library/asyncio-task.html and write a cheat sheet
```

The first word is the server name, the rest is the task. The skill runs `bin/jevagent.py`, the same loop as
`agent/jevloop.py` packaged to stand alone: it takes the server command from `.mcp.json`, lets Jev call only read-only
tools (tools that publish `readOnlyHint`, names that start with get/list/read/describe/search/fetch/find/show, never
anything on the never-list), and prints the answer plus one line of numbers. It needs `ANTHROPIC_API_KEY` and a Jev key
in the environment or in `./.env`; Claude Code's own subscription is not used, because the agent runs on the Messages
API where Jev can take turns, which a Claude Code session does not allow. First run of the packaged agent on the
seven-page task: 69.0s, 3 model turns, 8 tool calls of which Jev made 6, all seven pages named
(`agent-20260926-213518-jev`).

Settings (asked on install, or env vars):

| Setting | Env var | Default | Meaning |
| --- | --- | --- | --- |
| api_key | `AI_GATEWAY_API_KEY`, `OPENROUTER_API_KEY` or `JEVSIGHT_API_KEY` | none | Jev key (Vercel AI Gateway, OpenRouter or TypeSafe) |
| provider | `JEVSIGHT_PROVIDER` | whichever key is set | `vercel`, `openrouter` or `typesafe` |
| model | `JEVSIGHT_MODEL` | claude-opus-5-5 | the model the agent calls on the Messages API |
| threshold | `JEVSIGHT_THRESHOLD` | 0.4 | Jev makes the call itself when its top candidate has at least this probability |
| mode | `JEVSIGHT_MODE` | shadow | `shadow` predicts and logs only, `on` runs guesses early, `off` |
| alpha | `JEVSIGHT_ALPHA` | 0.25 | price of a wasted worker-second; lower means more speculation |
| extra_commands | `JEVSIGHT_EXTRA_COMMANDS` | none | command prefixes safe to run early |
| (proxy) | `JEVSIGHT_TASK` | none | the task text shown to Jev with the MCP trace |
| (proxy) | `JEVSIGHT_MAX_LAUNCH` | 2 | early MCP calls in flight at once |
| (proxy) | `JEVSIGHT_TRANSCRIPT_DIR` | Claude Code's folder for the cwd | where to find the session transcript for Claude's narration (`JEVSIGHT_TRANSCRIPT` names one file) |

## What Jev sees

The state is the task, every tool call so far with a result excerpt (the newest three at full length), and a few facts. Two things were added after the first races:

- **Claude's narration.** The words Claude writes between calls ("Default branch is `main`. Listing its tables.") go into the trace as `Claude says: "..."`. A prediction is made right after each result, and again the moment Claude narrates; the outcome log keeps both probabilities (`p_actual_before_narration`). Two sources:
  - A **feed** written by whatever drives Claude Code through `--output-format stream-json`: the stream emits each text block as its own event 0.3 to 0.5s before the tool call it precedes. `race/race.py` writes `jevsight-data/narration.jsonl` and points the proxy at it with `JEVSIGHT_NARRATION_FEED`.
  - The **session transcript** (hooks pass its path; the proxy finds the newest one for its working directory). Claude Code stamps the text 0.3 to 0.6s before the call but writes both to the file together when the call is emitted, so from this source the words arrive with the call. Jevsight puts them back in front of that call in the trace, which still helps the next prediction, but only the feed can make the announced call itself faster.

  `eval/replay_bench.py` models both predictions per step and reports top-1 accuracy before and after the narration; `--no-narration` replays the old state.
- **The MCP server's tool catalog.** Every tool with its required arguments, whether it may be run early, and its description, so Jev can map the task's words ("list the tables") onto the server's tools.
| (proxy) | `JEVSIGHT_READ_ONLY` | none | extra tool names (comma-separated) the proxy may run early |
| (proxy) | `JEVSIGHT_COOLDOWN` | 5 | seconds a Jev route rests after 3 failures in a row; use 2 for short races |

## What it will and won't run early

- Shell: read-only by construction (`rg`, `grep`, `find` without `-exec`/`-delete`, `ls`, `cat`, read-only `git`, `tsc --noEmit`, `mypy`, `pyright`, `eslint`/`ruff check` without `--fix`), commands you already allow in Claude Code (`permissions.allow`, e.g. `Bash(npm test)`), or listed in `extra_commands`.
- MCP: the read-only allowlist above plus `readOnlyHint` tools, minus the never list.
- Never: edits, writes, anything with shell operators or redirects, network or paid APIs, SQL, secrets.
- Any edit or unrecognized command (shell) or non-read-only call (MCP) bumps a version. Guesses from an older version are never served.

## Agent UI (TypeScript), more detail

A local web app. It runs the Claude / Claude+Jev loop and shows every turn as it happens:
neutral cards for the frontier model's turns, orange cards for Jev's decisions with a probability bar per candidate and
the commit threshold marked, tool rows with timings, a ticking scoreboard (wall, model turns, tool calls, tokens, Jev
cost), and the answer with the sources it named. Side-by-side mode runs Claude alone next to Claude+Jev on the same
task; replay plays any saved run back on the same timeline. Deep link for demos: `/?replay=<run>,<run>&speed=4`.

```bash
python3 agent/ui.py            # API on http://127.0.0.1:8765 (standard library; same harness and run dirs as jevloop.py)
cd web && npm install && npm run dev   # Next.js + TypeScript UI on http://localhost:3000
```

## Commands

- `/jevsight:stats`: hits, time saved, waste, top-1 accuracy, reliability table.
- `/jevsight:backtest`: replays your past sessions for this project in shadow mode.
- `python3 plugins/jevsight/bin/stats.py --events <dir>/events.jsonl`: same stats from the shell (works for proxy logs too).

## Layout

```
.claude-plugin/marketplace.json     marketplace listing
plugins/jevsight/                   the plugin
  hooks/hooks.json                  UserPromptSubmit, PreToolUse(Bash), PostToolUse, PostToolUseFailure
  bin/hook.py                       thin hook client (never blocks or fails a tool call)
  bin/daemon.py                     one per machine: predict, EV gate, run early, cache, replay (shell)
  bin/mcp_proxy.py                  stdio MCP proxy: predict, EV gate, run early, serve saved results
  bin/wrap_mcp.py                   rewrites a .mcp.json to go through the proxy
  bin/predictor.py                  Jev request (two Choice questions) + stand-in heuristic
  bin/narration.py                  tails the Claude Code transcript for Claude's words between calls
  bin/safety.py                     what shell commands are safe to run early
  bin/replay.py                     prints a saved result with the original exit code
tests/fake_mcp_server.py            Neon-shaped stdio MCP server for tests (no network)
tests/test_mcp_proxy.py             end-to-end proxy test, plain python3
tests/test_narration.py             transcript tail: partial lines, sidechains, newest-file discovery
tests/fake_claude.py                stand-in for the claude CLI: rehearse race.py without a login
tests/neon_smoke.py                 real Neon server through the proxy (needs NEON_API_KEY)
race/starter-next/                  default race app: Next.js one-shot, 58 failing tests, `npm run check` ~14-22s
race/broken-next/                   bug-fix race app
race/reference-next/                reference solution (not shown to agents)
race/starter/, race/reference/      quick TypeScript version (47 tests, checks ~4s)
race/race.py                        side-by-side race rig (apps: small, next, fix, neon, github, fetch)
eval/mcp_probe.py                   MCP speculation ceiling from one plain session
eval/bench.py, eval/replay_bench.py live and offline evals (shell and MCP)
```

## Notes

- With no key set, the Jevsight side uses a heuristic stand-in and the race header says so. Don't present those numbers as Jev.
- Logs: `$JEVSIGHT_DATA` (race runs) or the plugin data dir; `events.jsonl` has every prediction, launch, hit, miss and outcome. The proxy also writes `tools.json` there for the replay bench.
- python.org builds of Python on macOS ship without CA certificates until you run `Install Certificates.command`; the predictor falls back to `certifi` when it is installed, and `doctor.py` will tell you if TLS is the problem.

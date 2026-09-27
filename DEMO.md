# Jevsight demo script (5 minutes, real runs only)

Every number below names the run directory it comes from. Nothing is staged. If a live run goes badly on
camera, show the recorded run and say which one it is.

## Act 1: the problem, measured (45s)

Agents sit idle while tools run, and they spend a full model turn to say "next page". We measured where
speculation can and cannot help:

| task | perfect-predictor ceiling | source |
| --- | --- | --- |
| coding, Next.js one-shot | 0.8% of wall | `race-20260925-222959-1` |
| coding, bug fix | 3.8% | `race-20260926-000107-1` |
| Neon MCP schema walk | 6.9% | `race-20260926-011950-1` |
| web-fetch docs walk | 7.8-8.9% | `race-20260926-0303*` |

Coding agents batch edits and run the check 0s later: nothing to hide. MCP calls are sequential and each
needs an id from the last result, so that is where Jev gets a shot.

## Act 2: inside Claude Code, unmodified (90s)

`python3 race/race.py --app fetch` on split screen: plain Claude Code vs Claude Code + the Jevsight MCP proxy.
Same prompt, same model (`claude-opus-5-5`), same seven asyncio pages. Jev predicts the next fetch after each
result; the proxy runs it early and answers Claude's call from the saved result.

Recorded: `race-20260926-030845-1`. Jevsight side: 5 of 8 calls served in under 10ms, waited 3.2s vs the
baseline's 7.1s, same seven pages in both cheat sheets, 0 Jev errors. Four races in a row gave 5/8, 5/8, 5/8
after the first (3/8). Point on screen: green sub-second waits, HIT lines in the feed.

Say plainly: the ceiling here is ~8% of wall, and we captured about a third of it. Speculation hides tool
latency; it cannot remove Claude's turns.

## Act 3: when we own the loop, Jev takes the turns (90s)

`python3 agent/jevloop.py --driver both --app fetch`: the same task through the Anthropic API, same model.
Driver `llm` = Claude decides every call. Driver `jev` = after each result Jev picks the next call; if it is
confident, the loop runs it and Claude never spends a turn on it.

Recorded: `loop-20260926-032658-llm` vs `loop-20260926-033045-jev`.

| driver | wall | Claude turns | input tokens | tool calls |
| --- | --- | --- | --- | --- |
| Claude decides | 91.9s | 11 | 261,621 | 10 |
| Jev decides | 68.7s | 5 | 140,015 | 7 |

Jev committed 3 calls, declined 4, 0 errors, same seven pages, in every pair. Three full pairs on disk
(`loop-20260926-032658-llm`, `loop-20260926-033612-llm`, `loop-20260926-034357-llm`, `loop-20260926-033045-jev`, `loop-20260926-033612-jev`, `loop-20260926-034357-jev`):

| driver | runs | wall, each | wall, median | Claude turns | input tokens | tool calls | final write-up turn |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Claude decides | 3 | 91.9, 90.9, 85.9 | 90.9s | 11 | 263333 | 10.3 | 54s, 54s, 46s |
| Jev decides | 3 | 68.7, 70.6, 75.5 | 70.6s | 5 | 140034 | 7.0 | 48s, 50s, 54s |

The wall-time spread is the final write-up turn (46-54s, Claude's, on both sides), not the navigation. Turns and tokens are
the robust numbers: Jev takes 6 of 11 turns off Claude every time.

The line: System One (Jev, 0.4s, calibrated) takes the routine navigation; System Two (Claude) reads and
writes. Half the turns, same answer.

Say the caching caveat before anyone asks. With prompt caching on both sides (`loop-20260926-064947/065417/065839-llm`
vs `loop-20260926-070514/070624/070730-jev`, commit threshold 0.4, medians of 3): wall 83.3s vs 70.3s (-16%),
10 vs 4 Claude turns (-60%), 84.0k vs 68.4k billed-equivalent input tokens (-19%, cache writes at 1.25x, reads at 0.1x).
Caching already removes most of the re-read cost, so the bill drops a fifth, not a half; the turn cut stands. 13 Jev
commits across the three runs, every one the correct next page. Jev's own bill is about a tenth of a cent per run.

Then the stronger argument, the obvious alternative tested (`--driver cascade`, `loop-20260926-064947/065417/065839-cascade`,
cached): Haiku 4.5 takes the navigation turns with a navigation-only instruction, Opus 5.5 writes. Slower than plain Opus in
all six runs: median 109.9s, 32 turns, 30 tool calls, because Haiku paged the docs in 5,000-char slices every time; 72k
Opus-equivalent tokens for the write-up plus 127k Haiku-equivalent, against Jev's 68k Opus-equivalent total. A generative
small model substitutes its own habits; a classifier over enumerated candidates keeps Opus's navigation policy.

## Act 4: holds up when Jev fails (30s)

`race-20260926-012015-2` and `-012053-3`: Jev returned 429/503 on 60% and 80% of calls (TypeSafe's upstream
was degraded; we probed it). The jevsight side still finished with the same answer, it just relayed. Show the
`predict_error` count in the header. The loop does the same: a Jev failure hands the turn to Claude.

## Act 5: numbers and install (45s)

- `eval/bench.py` and `eval/replay_bench.py` tables; the calibration note (Jev overconfident: top choice at
  0.94 was right 2 of 3 times on Neon; ECE 0.28-0.31 on fetch).
- Install: `/plugin install jevsight@jevsight`; wrap any stdio MCP server with one line in `.mcp.json`
  (`plugins/jevsight/bin/wrap_mcp.py` does it for you).

## Commands to have ready

```bash
JEVSIGHT_COOLDOWN=2 python3 race/race.py --app fetch          # act 2, live
python3 agent/jevloop.py --driver both --app fetch            # act 3, live (~3 min)
python3 eval/bench.py ~/jevsight-races/race-20260926-030845-1 # act 5
```

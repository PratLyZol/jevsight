# Jevsight demo script (5 minutes, real runs only)

Every number below names the run directory it comes from. Nothing is staged. If a live run goes badly on camera,
replay the recorded run in the UI and say which one it is.

## Act 1: the problem (40s)

Open the UI (`python3 agent/ui.py`, `cd web && npm run dev`). Replay `loop-20260926-065839-llm` alone at 4×.
Point at the blue cards: ten Claude turns whose whole output is "fetch the next page", each one re-reading the
entire conversation and thinking for three seconds. Then the 50-second write-up. A third of the run is spent
deciding the obvious.

## Act 2: Jev takes the turn (90s)

Replay `loop-20260926-065839-llm` and `loop-20260926-070514-jev` side by side at 4×. Orange cards are Jev: half a
second, a probability per candidate, the threshold line at 0.4. "Committed at p 0.79" means Jev made the call and
Claude never took that turn. "Declined" means the turn went back to Claude. Read the comparison tiles when both
finish: 84.7s → 70.3s, 11 → 4 model turns, 262k → 111k tokens, same seven sources.

Say the caching caveat before anyone asks: with prompt caching on, the bill drops about a fifth, not a half. The
turn count is the honest headline.

## Act 3: the obvious alternative (45s)

Replay `loop-20260926-065839-cascade` (Haiku navigates, Opus writes). Thirty-one Haiku turns, 700k Haiku tokens,
110 seconds: slower than Opus alone, because Haiku read the docs in 5,000-character slices. A classifier over
enumerated candidates inherits Opus's own page size; a small generative model substitutes its habits.

## Act 4: Claude Code versus the agent, live if the network is kind (60s)

Mode "Claude Code vs Claude + Jev", pick `fetch-long`, "Use the benchmark task", "Start both". A real Claude Code
session runs on the left, the agent on the right. Recorded fallback (`/?versus=race-20260926-203256-1,loop-20260926-205230-jev&speed=4`):
Claude Code 159.5s, 25 turns, $1.42; the agent 109.8s, 10 model turns, Jev right on every one of its 9 commits, all
14 sources on both sides. Say once that the harnesses differ; the model, prompt, server and start time do not.

## Act 5: what made it work, and what it can't do (45s)

- Ids listed in the task are pinned in the candidate window; without that, page links crowded out the reading list.
- Long results are shown to Jev as head and tail with the omission marked, so a server's "truncated, continue
  from N" notice is visible.
- Claude's own words between calls go into Jev's question.
- A wrong pick is one extra read-only page, never a wrong answer; nothing that writes or costs money is a candidate.
- Limits: small samples, tasks where the next step is listable, Jev runs overconfident (we measure it).

Close on the numbers: half the turns, same answer, fails soft, beats the small-model cascade.

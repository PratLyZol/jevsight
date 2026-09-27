# Prompt for Claude: build the Jevsight side-by-side replay

Paste everything below the line into Claude (claude.ai with artifacts, or Claude Code) and attach
`demo/replay_data.json`. Claude cannot render video directly, so ask for a self-contained HTML page that
animates the real traces; then screen-record it (QuickTime: File > New Screen Recording, or OBS) at 1920x1080.
Play it at 2x for the 5-minute cut; the page has a speed control.

---

Build a single self-contained HTML file (no external dependencies except Google Fonts) that replays two
agent runs side by side from the attached `replay_data.json`, in real time, as an animated split screen that I
will screen-record for a demo video. This is real data from real runs; do not invent events, times or numbers.
Everything shown must come from the file.

## What the data is

One comparison, three independent pairs, same task (`task`: an agent reads seven Python asyncio documentation
pages through an MCP "fetch" tool and writes a cheat sheet), same model (`model`). `what_differs` explains the
two sides: `claude` lets Claude decide every tool call, one model turn per call; `claude_plus_jev` asks Jev, a
fast calibrated classifier, which call comes next after every tool result, and if Jev is confident the loop
executes that call itself, so Claude never spends a turn on it.

`pairs[i].claude` and `pairs[i].claude_plus_jev` each have `segments` (the timeline) and `breakdown` (the
numbers). A segment has `s` and `e` (start and end, seconds from the run's start), `kind`, `who`, `label`, and
sometimes `detail`, `text`, `p`. `segment_kinds` documents the kinds: `think` is Claude deciding its next call,
`tool` is a fetch in flight (`who: claude` asked for it, `who: jev` committed it without a Claude turn), `jev` is
a Jev prediction call, `write` is Claude writing the final cheat sheet. `means` and `deltas` are computed over
the three pairs.

## The page

A pair selector (keys 1/2/3, default pair 2). Split screen: left lane = `claude`, right lane = `claude_plus_jev`.
A shared clock runs from 0 to the longer lane's `wall_s`. Controls: play/pause, speed 1x/2x/4x, a scrubber,
restart. Start paused at t=0 with a 3-second title card naming the task, the model, and what differs.

Each lane, top to bottom:
1. A live "terminal" that appends one line per segment when the clock passes `s`, styled by kind: think = dim
   italic "Claude deciding..." with an elapsed counter that stops at `e`; tool = monospace label with a spinner
   that becomes the measured duration at `e`, and on the right lane a bright "JEV" tag when `who: jev` so it is
   obvious no Claude turn happened; jev = a short tag with the probability; write = "writing the cheat
   sheet..." with a counter. Auto-scroll, keep the last ~14 lines visible.
2. A horizontal timeline of the whole run with two rows (claude, jev), blocks colored by kind, a moving playhead.
3. Live counters that update as segments end: Claude turns so far, seconds Claude spent deciding so far
   (sum of `think`), seconds waiting on tools so far, and on the right lane Jev commits so far.

When the shorter lane finishes, stamp it "done at Ns" and let the other continue. When both finish, fade in a
scoreboard from the two `breakdown` objects: wall, Claude turns, navigation turns, thinking seconds, tool wait,
write-up seconds, input tokens. Below it, one line from `deltas` and `means` for the three pairs together:
navigation phase 46% lower, turns 55% fewer, input tokens 47% fewer, wall 20% lower, write-up the same.

Make the point visible without words: during the navigation phase the right lane's tool lines arrive in a
quick run while the left lane shows "Claude deciding..." between every fetch. Then both lanes spend ~50s on
the write-up, which should read as the same work on both sides.

## Style

Dark, high contrast, 1920x1080, safe to record at 2x. One accent for Claude, one for Jev, both readable on a
phone: terminal text at least 20px, counters at least 36px. Monospace for the terminals (JetBrains Mono or IBM
Plex Mono), a clean sans for headings. No emoji, no flashing. Put the run names from each pair's `run` fields
in small type at the bottom so the video is auditable.

## Ground rules

- Every number and event comes from the file. If something is missing, leave it blank rather than fake it.
- The clock is real time: a 0.6 s fetch takes 0.6 s at 1x.
- One file, no build step. Inline the JSON verbatim if you prefer.

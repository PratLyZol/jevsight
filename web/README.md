# Jevsight agent UI

Next.js + TypeScript front end for the Claude / Claude+Jev loop in `../agent/jevloop.py`.

```bash
python3 ../agent/ui.py      # API on http://127.0.0.1:8765 (standard library, no install)
npm install && npm run dev  # UI on http://localhost:3000
```

Two views: the agent loop (live or replay) and the Claude Code race (replay of `race/race.py` runs, both sides at once).
Deep links: `/?replay=<run>,<run>&speed=4` and `/?race=<race>&speed=4`. Set `NEXT_PUBLIC_API_BASE` if the API runs elsewhere. Live runs write the same run directories and
`loops.jsonl` records as the command-line harness; replay plays any of them back on the same timeline.

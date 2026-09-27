---
name: stats
description: Show Jevsight speculation stats for this project (hits, time saved, waste, prediction accuracy). Use when the user asks how Jevsight is doing or what it saved.
---

Run this command and show the user its output as a short summary:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/stats.py" --cwd "$PWD"
```

Report: hit rate, time saved, time wasted, top-1 command accuracy, and the reliability rows (predicted probability vs how often that command actually came next). Keep it to a few lines.

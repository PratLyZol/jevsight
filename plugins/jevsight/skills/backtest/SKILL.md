---
name: backtest
description: Replay the user's past Claude Code sessions for this project through Jevsight in shadow mode and estimate what it would have saved. Use when the user asks what Jevsight would save them.
---

Run this command and summarize the output for the user:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/backtest.py" --project "$PWD"
```

Report how many shell commands were predictable, the estimated time saved, and the caveats the script prints.

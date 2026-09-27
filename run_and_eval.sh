#!/usr/bin/env bash
# One command: race plain Claude Code vs Claude Code + Jevsight, then benchmark it.
# Usage: ./run_and_eval.sh [number_of_races]      (APP=neon ./run_and_eval.sh 3 for the Neon MCP race)
set -euo pipefail
cd "$(dirname "$0")"
N="${1:-1}"
APP="${APP:-fix}"
CFG="$HOME/.jevsight-claude"

if [ ! -d "$CFG" ] || ! CLAUDE_CONFIG_DIR="$CFG" claude -p "reply with ok" >/dev/null 2>&1; then
  echo "One-time setup: log in to a clean Claude Code config (no personal hooks, plugins or MCP servers)."
  echo "A Claude Code session opens now. Type /login, finish the login, then /exit."
  mkdir -p "$CFG"
  CLAUDE_CONFIG_DIR="$CFG" claude
fi

pkill -f "jevsight/bin/daemon.py" 2>/dev/null || true
python3 plugins/jevsight/bin/doctor.py | sed -n "1,8p" || echo "(doctor check failed; racing anyway)"

python3 race/race.py --app "$APP" --repeat "$N" --claude-config "$CFG"

mkdir -p eval/out
for R in $(ls -d "$HOME"/jevsight-races/race-* | tail -n "$N"); do
  name=$(basename "$R")
  python3 eval/bench.py "$R" --md "eval/out/$name.bench.md" --json "eval/out/$name.bench.json" >/dev/null
  python3 eval/replay_bench.py "$R" --md "eval/out/$name.replay.md"
done
echo
echo "Done. Reports are in eval/out/. Tell Claude: done."

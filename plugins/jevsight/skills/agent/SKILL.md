---
name: agent
description: Run a read-only research task with the Jevsight agent, where Claude keeps the thinking and Jev (a calibrated classifier) takes the routine tool calls. Use when the user says "use the jev agent", "run this with jevsight", or asks for a research task over one of the project's MCP servers to be done with fewer model turns.
---

The user gives a server name from this project's `.mcp.json` and a task, for example `/jevsight:agent fetch Read https://docs.python.org/3/library/asyncio.html and https://docs.python.org/3/library/asyncio-task.html and write a cheat sheet`.

1. Take the first word of the arguments as the server name and the rest as the task. If the task is missing, ask for it. If `.mcp.json` has no such server, list the stdio servers it does have and stop.
2. Run, from the project directory:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/jevagent.py" --mcp-json "$PWD/.mcp.json" --name "<server>" --task "<task>" --quiet
```

   It needs `ANTHROPIC_API_KEY` and a Jev key (`AI_GATEWAY_API_KEY`, `OPENROUTER_API_KEY` or `JEVSIGHT_API_KEY`) in the environment or in `./.env`. If it exits saying a key is missing, tell the user which one and stop; never ask them to paste a key into the chat.
3. Show the user the answer the script prints, then its last line as one sentence: how many model turns it took, how many tool calls Jev made for Claude, and the run directory.

The agent only ever calls read-only tools: tools that publish `readOnlyHint`, plus names that start with get/list/read/describe/search/fetch/find/show, never anything that creates, deletes, resets, provisions, migrates or returns a connection string. It runs the task itself on the Anthropic API; do not call the tools yourself in this conversation.

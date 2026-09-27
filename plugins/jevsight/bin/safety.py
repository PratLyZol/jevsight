"""Decide which shell commands are safe to run before Claude asks for them.

A command is speculable only if it is read-only by construction (a fixed list of
search, git-read and type-check commands) or the user already allows it in their
Claude Code permission rules (for example "Bash(npm test)"), or it matches a
prefix the user listed in the plugin's extra_commands option.
Anything with shell operators, redirects or substitutions is never speculated.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re

# Suffixes Claude often appends that do not change what the command does.
_SUFFIXES = [
    re.compile(r"\s+2>&1$"),
    re.compile(r"\s*\|\s*(head|tail)(\s+-n)?\s+-?\d+$"),
]
_CD_PREFIX = re.compile(r"^cd\s+(\"[^\"]+\"|'[^']+'|[^\s;&|]+)\s*&&\s*(.+)$")
# Env assignments that do not change what a command computes.
HARMLESS_ENV = {"NEXT_TELEMETRY_DISABLED", "CI", "FORCE_COLOR", "NO_COLOR", "TERM", "NPM_CONFIG_UPDATE_NOTIFIER",
                "npm_config_update_notifier", "NODE_NO_WARNINGS", "COLUMNS", "PAGER", "GIT_PAGER"}
_ENV_PREFIX = re.compile(r"^((?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)+)(.*)$")
_META = re.compile(r"[;&|<>`$\n\\]")

_READ_ONLY = [
    r"rg\b", r"grep\b", r"ls\b", r"cat\b", r"head\b", r"tail\b", r"wc\b", r"pwd$", r"tree\b",
    r"find\b(?!.*\s-(delete|exec|execdir|ok|okdir|fprint|fprintf|fls)\b)",
    r"git\s+(status|diff|log|show|ls-files|blame)\b",
    r"(npx\s+)?tsc\b.*--noEmit\b",
    r"mypy\b", r"pyright\b",
    r"(npx\s+)?eslint\b(?!.*--fix)",
    r"ruff\s+check\b(?!.*--fix)",
]
_READ_ONLY_RE = [re.compile("^" + p) for p in _READ_ONLY]


def normalize(cmd: str) -> str:
    return " ".join((cmd or "").strip().split())


def split_command(cmd: str):
    """Split into (prefix, core, suffix): prefix = `cd X && ` and harmless env assignments,
    suffix = ` 2>&1` and `| head/tail -N`. Returns None if an env var could change the result."""
    c = normalize(cmd)
    prefix = ""
    m = _CD_PREFIX.match(c)
    if m:
        prefix = c[: len(c) - len(m.group(2))]
        c = m.group(2)
    m = _ENV_PREFIX.match(c)
    if m:
        names = [a.split("=", 1)[0] for a in m.group(1).split()]
        if any(n not in HARMLESS_ENV for n in names):
            return None
        prefix += m.group(1)
        c = m.group(2)
    suffix = ""
    changed = True
    while changed:
        changed = False
        for rx in _SUFFIXES:
            mm = rx.search(c)
            if mm:
                suffix = c[mm.start():] + suffix
                c = c[: mm.start()]
                changed = True
    return prefix, c.strip(), suffix


def canonical(cmd: str) -> str:
    """The part that determines the result: used as the cache key."""
    parts = split_command(cmd)
    return parts[1] if parts else normalize(cmd)


def core(cmd: str) -> str:
    """Strip a leading `cd X &&`, harmless env assignments and harmless trailing suffixes."""
    parts = split_command(cmd)
    if parts:
        return parts[1]
    c = normalize(cmd)
    m = _CD_PREFIX.match(c)
    if m:
        c = m.group(2)
    changed = True
    while changed:
        changed = False
        for rx in _SUFFIXES:
            new = rx.sub("", c)
            if new != c:
                c, changed = new, True
    return c.strip()


def _settings_allow_rules(cwd: str) -> list:
    files = [
        os.path.join(cwd, ".claude", "settings.json"),
        os.path.join(cwd, ".claude", "settings.local.json"),
        os.path.expanduser("~/.claude/settings.json"),
    ]
    extra = os.environ.get("JEVSIGHT_SETTINGS_FILE")
    if extra:
        files.append(extra)
    rules = []
    for f in files:
        try:
            with open(f) as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        for r in (data.get("permissions") or {}).get("allow") or []:
            if isinstance(r, str) and r.startswith("Bash(") and r.endswith(")"):
                rules.append(r[5:-1])
    return rules


def _rule_match(rule: str, cmd: str) -> bool:
    if rule.endswith(":*"):
        base = rule[:-2]
        return cmd == base or cmd.startswith(base + " ")
    if "*" in rule:
        return fnmatch.fnmatchcase(cmd, rule)
    return cmd == rule


def extra_prefixes() -> list:
    raw = os.environ.get("CLAUDE_PLUGIN_OPTION_EXTRA_COMMANDS") or os.environ.get("JEVSIGHT_EXTRA_COMMANDS") or ""
    raw = raw.strip()
    if not raw:
        return []
    try:
        val = json.loads(raw)
        if isinstance(val, list):
            return [normalize(str(v)) for v in val if str(v).strip()]
    except ValueError:
        pass
    return [normalize(p) for p in re.split(r"[,\n]", raw) if p.strip()]


def classify(cmd: str, cwd: str):
    """Return 'read_only', 'allowed', or None (never speculate)."""
    if split_command(cmd) is None:
        return None  # sets an env var that could change the result
    c = core(cmd)
    if not c or _META.search(c):
        return None
    for rx in _READ_ONLY_RE:
        if rx.match(c):
            return "read_only"
    for p in extra_prefixes():
        if c == p or c.startswith(p + " "):
            return "allowed"
    for rule in _settings_allow_rules(cwd):
        if _rule_match(rule, c):
            return "allowed"
    return None

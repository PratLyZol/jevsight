#!/usr/bin/env python3
"""Check that Jev is reachable: sends one real prediction and prints the raw answer."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import api_key, data_dir, mode, sock_path  # noqa: E402
from predictor import JevPredictor, PredictionError, render_state  # noqa: E402


def load_dotenv():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    path = os.path.join(root, ".env")
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if v.strip():
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main():
    load_dotenv()
    print("data dir:  ", data_dir())
    print("socket:    ", sock_path())
    print("mode:      ", mode())
    print("api key:   ", "set" if api_key() else "MISSING (set AI_GATEWAY_API_KEY, OPENROUTER_API_KEY or JEVSIGHT_API_KEY)")
    p = JevPredictor()
    print("provider:  ", p.provider)
    print("endpoint:  ", p.url, "model:", p.model)
    if not api_key():
        return 1
    state = render_state("Implement SPEC.md until npm test passes.",
                         ["Read SPEC.md", "Edit src/money.ts"],
                         {"last_action": "edit_file", "files_edited_since_last_check": "yes"})
    cands = ["npm test", "npm run typecheck", "git status", "ls"]
    body = p.request_body(state, cands)
    try:
        raw = p.call(body)
    except PredictionError as e:
        print("ERROR:", e)
        return 1
    print("raw response:")
    print(json.dumps(raw, indent=2)[:3000])
    try:
        print("parsed:", json.dumps(p.predict(state, cands), indent=2))
    except PredictionError as e:
        print("parse error:", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())

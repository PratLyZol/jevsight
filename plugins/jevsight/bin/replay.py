#!/usr/bin/env python3
"""Print the saved output of a speculative run and exit with its code.

Claude Code runs this in place of a command Jevsight already ran. If the
speculative run is still going, it waits for it to finish.
"""
import json
import os
import shutil
import sys
import time


def main():
    job_dir = sys.argv[1]
    status_path = os.path.join(job_dir, "status.json")
    deadline = time.time() + 600
    while not os.path.exists(status_path):
        if time.time() > deadline:
            sys.stderr.write("jevsight: speculative run did not finish\n")
            return 124
        time.sleep(0.02)
    with open(status_path) as f:
        status = json.load(f)
    for name, stream in (("stdout", sys.stdout.buffer), ("stderr", sys.stderr.buffer)):
        try:
            with open(os.path.join(job_dir, name), "rb") as f:
                shutil.copyfileobj(f, stream)
        except OSError:
            pass
        stream.flush()
    rc = status.get("rc", 1)
    return rc if isinstance(rc, int) and 0 <= rc < 256 else 1


if __name__ == "__main__":
    sys.exit(main())

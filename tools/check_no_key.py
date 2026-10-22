#!/usr/bin/env python3
"""
Fails if the FEC API key (from the FEC_API_KEY environment variable) appears
anywhere in the project tree, the data files or the response cache.

    export FEC_API_KEY=...
    python3 tools/check_no_key.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules"}


def main():
    key = os.environ.get("FEC_API_KEY", "").strip()
    if not key:
        print("FEC_API_KEY is not set in this shell; nothing to scan for.")
        sys.exit(2)
    hits = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            path = os.path.join(base, name)
            try:
                with open(path, "rb") as f:
                    if key.encode() in f.read():
                        hits.append(os.path.relpath(path, ROOT))
            except OSError:
                continue
    if hits:
        print("The API key appears in:")
        for h in hits:
            print("  " + h)
        sys.exit(1)
    print("No API key found in the project tree, data files or cache.")


if __name__ == "__main__":
    main()

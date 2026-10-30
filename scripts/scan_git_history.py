#!/usr/bin/env python3
"""Scan reachable Git commit patches for common exposed-secret patterns.

Run after `git fetch --all` in a real checkout. Values are never printed.
This is a targeted guard, not a substitute for a provider-aware secret scanner.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\b(?:xox[baprs]-)[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\b(?:sk_live_|rk_live_)[A-Za-z0-9]{16,}\b"),
]
ASSIGNMENT = re.compile(
    r"(?im)^\+\s*(?:QLOO_API_KEY|LLM_API_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY)\s*[:=]\s*['\"]?([^\s'\"#]+)"
)
PLACEHOLDERS = {"", "your-key", "your_api_key", "replace-me", "changeme", "<secret>", "<your-key>"}


def main() -> int:
    root = Path.cwd()
    if not (root / ".git").exists():
        print("ERROR: run this command from a Git checkout with .git present.", file=sys.stderr)
        return 2
    proc = subprocess.run(
        ["git", "log", "--all", "--format=commit %H", "--patch", "--no-ext-diff", "--binary"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if proc.returncode:
        print("ERROR: git log failed; fetch all refs and retry.", file=sys.stderr)
        return 2
    text = proc.stdout.decode("utf-8", errors="replace")
    findings: list[str] = []
    current_commit = "unknown"
    for line_no, line in enumerate(text.splitlines(), start=1):
        if line.startswith("commit "):
            current_commit = line.removeprefix("commit ")[:12]
        for pattern in PATTERNS:
            if pattern.search(line):
                findings.append(f"commit {current_commit}, patch line {line_no}: credential/private-key pattern")
                break
        m = ASSIGNMENT.search(line)
        if m and m.group(1).strip("'\"").lower() not in PLACEHOLDERS:
            findings.append(f"commit {current_commit}, patch line {line_no}: populated provider-key assignment")
    if findings:
        print("Potential secret exposure found; do not distribute until reviewed:", file=sys.stderr)
        for finding in sorted(set(findings)):
            print(" - " + finding, file=sys.stderr)
        return 1
    print("No targeted secret patterns found in patches reachable from local Git refs.")
    print("Note: scan binary blobs/provider-specific formats separately; this is not a guarantee of no secrets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

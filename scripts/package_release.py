#!/usr/bin/env python3
"""Create a sanitized StockRescue release archive.

The packager deliberately walks the working tree rather than trusting that an
ignored local file was excluded from a manually-created ZIP. It omits runtime
artifacts and refuses to package common provider-token patterns or populated
provider-key environment assignments.
"""
from __future__ import annotations

import argparse
import re
import sys
import subprocess
import zipfile
from pathlib import Path

EXCLUDED_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".next", "dist", "build", ".tox",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".sqlite", ".sqlite3", ".db", ".log"}
EXCLUDED_NAMES = {".env", ".env.local", ".env.production", ".DS_Store"}

SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\b(?:xox[baprs]-)[A-Za-z0-9-]{20,}\b"),
]
ASSIGNMENT = re.compile(
    r"(?im)^\s*(?:QLOO_API_KEY|LLM_API_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY)\s*[:=]\s*['\"]?([^\s'\"#]+)"
)
PLACEHOLDERS = {"", "your-key", "your_api_key", "replace-me", "changeme", "<secret>", "<your-key>"}


def excluded(rel: Path) -> bool:
    if any(part in EXCLUDED_DIRS for part in rel.parts):
        return True
    if rel.name in EXCLUDED_NAMES:
        return True
    if rel.suffix.lower() in EXCLUDED_SUFFIXES:
        return True
    # Keep the documented placeholder file, but no other .env variant.
    if rel.name.startswith(".env") and rel.name != ".env.example":
        return True
    return False


def secret_findings(rel: Path, data: bytes) -> list[str]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return []
    findings: list[str] = []
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            findings.append(f"{rel}: token/private-key pattern detected")
    if rel.name != ".env.example":
        for match in ASSIGNMENT.finditer(text):
            value = match.group(1).strip().strip("'").strip('"')
            if value.lower() not in PLACEHOLDERS and len(value) >= 8:
                findings.append(f"{rel}: populated provider-key assignment detected")
                break
    return findings


def collect_files(root: Path) -> list[tuple[Path, Path]]:
    collected = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if excluded(rel):
            continue
        collected.append((path, rel))
    return collected


def package(root: Path, output: Path) -> int:
    root = root.resolve()
    output = output.resolve()
    history_scanner = root / "scripts" / "scan_git_history.py"
    if (root / ".git").exists() and history_scanner.exists():
        scan = subprocess.run([sys.executable, str(history_scanner)], cwd=root,
                              text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if scan.stdout:
            print(scan.stdout.rstrip())
        if scan.returncode:
            if scan.stderr:
                print(scan.stderr.rstrip(), file=sys.stderr)
            print("Release archive refused until Git-history findings are reviewed.", file=sys.stderr)
            return 4
    else:
        print("WARNING: no Git history available; only current release files can be scanned.", file=sys.stderr)
    files = collect_files(root)
    findings = []
    for source, rel in files:
        findings.extend(secret_findings(rel, source.read_bytes()))
    if findings:
        print("Release archive refused; review these findings:", file=sys.stderr)
        for finding in findings:
            print(f" - {finding}", file=sys.stderr)
        return 2

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source, rel in files:
            archive.write(source, Path(root.name) / rel)
    with zipfile.ZipFile(output) as archive:
        bad = [name for name in archive.namelist()
               if any(part in EXCLUDED_DIRS for part in Path(name).parts)
               or Path(name).name in EXCLUDED_NAMES
               or (Path(name).name.startswith(".env") and Path(name).name != ".env.example")
               or Path(name).suffix.lower() in EXCLUDED_SUFFIXES]
        if bad:
            output.unlink(missing_ok=True)
            print("Archive inspection found forbidden paths: " + ", ".join(bad), file=sys.stderr)
            return 3
    print(f"Created {output} with {len(files)} files; runtime artifacts and detected secrets excluded.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    output = args.output or (args.root / "dist" / "stockrescue-release.zip")
    return package(args.root, output)


if __name__ == "__main__":
    raise SystemExit(main())

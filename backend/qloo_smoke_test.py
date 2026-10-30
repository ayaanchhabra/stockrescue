"""Live Qloo smoke test through the event-supported Qloo harness CLI.

Prerequisites (see the official event kit):
  * Node.js 22.19.0 or newer
  * @qloo/qloo-harness 0.1.26 or newer (`npm install --global @qloo/qloo-harness`)
  * `qloo setup --qloo` completed with an individually attributable event key,
    or QLOO_API_KEY supplied in the shell environment.

This script intentionally does not make direct HTTP requests. It uses the
supported `qloo api` CLI surface and prints only sanitized response metadata.
The exact `qloo api` command set is available through `qloo api --help`.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from typing import Any

MIN_VERSION = (0, 1, 26)


def _version_tuple(value: str) -> tuple[int, int, int] | None:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", value)
    return tuple(map(int, match.groups())) if match else None


def _run(args: list[str], *, timeout: int = 45) -> tuple[int, Any | None, str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return 124, None, "timeout"
    except OSError as exc:
        return 127, None, type(exc).__name__
    payload = None
    if result.stdout.strip():
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            payload = None
    # Never echo CLI stderr/stdout on failure: providers may include request or
    # account metadata. Return only the process status and exception category.
    category = "ok" if result.returncode == 0 else "cli_error"
    return result.returncode, payload, category


def _entities(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    results = payload.get("results", payload.get("data", []))
    if isinstance(results, dict):
        results = results.get("entities", results.get("results", []))
    return [item for item in results if isinstance(item, dict)] if isinstance(results, list) else []


def main() -> int:
    cli = shutil.which("qloo")
    if not cli:
        print("BLOCKED: qloo CLI not found. Install @qloo/qloo-harness 0.1.26+ and configure it with `qloo setup --qloo`.")
        return 2

    code, version_output, category = _run([cli, "--version"], timeout=10)
    if code != 0 or not isinstance(version_output, (str, dict, list)):
        # Some CLI releases write the version as plain text; capture it without
        # emitting any other command output.
        try:
            version_result = subprocess.run([cli, "--version"], capture_output=True, text=True, timeout=10)
            version_text = version_result.stdout.strip() or version_result.stderr.strip()
        except Exception:
            version_text = ""
    else:
        version_text = version_output if isinstance(version_output, str) else json.dumps(version_output)
    parsed = _version_tuple(version_text)
    if parsed is None or parsed < MIN_VERSION:
        print("BLOCKED: qloo CLI version could not be verified or is older than 0.1.26.")
        return 2
    print(f"Qloo harness CLI: {'.'.join(map(str, parsed))} (minimum {'.'.join(map(str, MIN_VERSION) )})")

    # This invocation is documented by Qloo's official CLI workflow starter.
    code, search_payload, category = _run([
        cli, "api", "search", "--query", "1984", "--type", "book", "--take", "3", "--json"
    ])
    if code != 0:
        print(f"BLOCKED/FAILED: qloo api search did not complete (CLI exit {code}, {category}). Check `qloo api --help` and `qloo setup --status`.")
        return 1
    book_entities = _entities(search_payload)
    print(f"SEARCH: success; result_count={len(book_entities)}")
    if not book_entities:
        print("Search call succeeded but returned no book entities; Insights test cannot proceed.")
        return 0

    entity_id = book_entities[0].get("entity_id") or book_entities[0].get("id")
    if not isinstance(entity_id, str) or not entity_id:
        print("FAILED: search response contained no usable entity identifier.")
        return 1

    # The CLI maps endpoint parameters to kebab-case flags. Inspect the local
    # command's help when a harness release changes its generated flag schema.
    for kind in ("movie", "artist"):
        code, payload, category = _run([
            cli, "api", "insights",
            "--filter-type", f"urn:entity:{kind}",
            "--signal-interests-entities", entity_id,
            "--take", "2", "--feature-explainability", "true", "--json",
        ])
        if code != 0:
            print(f"BLOCKED/FAILED: qloo api insights for {kind} did not complete (CLI exit {code}, {category}). Check `qloo api --help`.")
            return 1
        results = _entities(payload)
        print(f"INSIGHTS {kind}: success; result_count={len(results)}")
        if results:
            query = results[0].get("query")
            print(f"  affinity_field_returned={isinstance(query, dict) and 'affinity' in query}")

    print("LIVE QLOO HARNESS CHECK PASSED. This verifies the supported CLI surface, not the backend's direct-HTTP transport.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

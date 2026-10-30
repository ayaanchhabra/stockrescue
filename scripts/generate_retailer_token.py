#!/usr/bin/env python3
"""Generate one strong retailer bearer token and its environment-safe hash."""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets

parser = argparse.ArgumentParser()
parser.add_argument("retailer_id", help="Stable retailer identifier (e.g. demo)")
args = parser.parse_args()
token = secrets.token_urlsafe(32)
digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
print("Save the bearer token securely; it is shown only once:")
print(f"Authorization: Bearer {token}")
print("Set this environment variable (hash only; do not store the raw token):")
print("RETAILER_API_TOKEN_HASHES=" + json.dumps({digest: args.retailer_id}, separators=(",", ":")))

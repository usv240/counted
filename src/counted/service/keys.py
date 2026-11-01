"""API keys for Counted-as-a-service. Keys are shown once and stored only as SHA-256 hashes.

Roles map to Cedar principals: `service` (default), `caseworker`, `certifier` (requires the admin token).
Storage is a JSON file locally; set COUNTED_KEYS_TABLE to use DynamoDB in production.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
from pathlib import Path

import boto3

from ..config import REGION

_FILE = Path(os.getenv("COUNTED_KEYS_FILE", Path(__file__).resolve().parents[3] / ".keys.json"))
_TABLE = os.getenv("COUNTED_KEYS_TABLE")
_lock = threading.Lock()
ROLES = {"service", "caseworker", "certifier"}


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _load() -> dict:
    return json.loads(_FILE.read_text()) if _FILE.exists() else {}


def issue(name: str, role: str = "service") -> dict:
    if role not in ROLES:
        raise ValueError(f"role must be one of {sorted(ROLES)}")
    key = "ct_" + secrets.token_urlsafe(24)
    record = {"name": name[:80], "role": role, "created": int(time.time()), "calls": 0}
    if _TABLE:
        boto3.resource("dynamodb", region_name=REGION).Table(_TABLE).put_item(Item={"key_hash": _hash(key), **record})
    else:
        with _lock:
            data = _load()
            data[_hash(key)] = record
            _FILE.write_text(json.dumps(data, indent=1))
    return {"api_key": key, **record}


def lookup(key: str | None) -> dict | None:
    if not key:
        return None
    h = _hash(key)
    if _TABLE:
        item = boto3.resource("dynamodb", region_name=REGION).Table(_TABLE).get_item(Key={"key_hash": h}).get("Item")
        return dict(item) if item else None
    with _lock:
        data = _load()
        rec = data.get(h)
        if rec:
            rec["calls"] += 1
            _FILE.write_text(json.dumps(data, indent=1))
        return rec

#!/usr/bin/env python3
"""Verifier for Broken Stack Lab. Standard library only.

Exit code 0 = every check passed, 1 = at least one failed.
Usage:  python3 verify.py [--quick] [--base-url http://localhost:8080]
  --quick   skip the (slower) Postgres restart persistence check
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ERROR_MARKERS = [
    "cache read failed",
    "cache write failed",
    "cache invalidation failed",
    "redis check failed",
    "postgres check failed",
    "database error",
]


def http(base, method, path, body=None, timeout=5):
    """Return (status_code, parsed_json_or_None). Never raises on HTTP errors."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw, code = resp.read(), resp.status
    except urllib.error.HTTPError as err:
        raw, code = err.read(), err.code
    except Exception:
        return None, None
    try:
        return code, json.loads(raw)
    except ValueError:
        return code, None


def compose(*args):
    try:
        return subprocess.run(
            ["docker", "compose", *args], cwd=HERE, capture_output=True, text=True, timeout=120
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(args, 1, stdout="", stderr=str(exc))


def wait_healthy(base, seconds=60):
    deadline = time.time() + seconds
    while time.time() < deadline:
        code, _ = http(base, "GET", "/health")
        if code == 200:
            return True
        time.sleep(2)
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    results = []

    def check(name, ok, detail=""):
        results.append(ok)
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))

    start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    marker = f"verify-{uuid.uuid4().hex[:8]}"

    # 1. Health endpoint reports both dependencies OK
    code, body = http(base, "GET", "/health")
    check("health endpoint returns 200 with postgres and redis ok",
          code == 200 and body == {"postgres": "ok", "redis": "ok"}, f"status={code} body={body}")

    # 2. Write path
    code, body = http(base, "POST", "/notes", {"text": marker})
    check("POST /notes creates a note (201)", code == 201 and bool(body and body.get("id")), f"status={code}")

    # 3. Read path hits the database after the write invalidated the cache
    code, body = http(base, "GET", "/notes")
    texts = [n.get("text") for n in (body or {}).get("notes", [])]
    check("GET /notes returns the new note", code == 200 and marker in texts, f"status={code}")

    # 4. Caching actually works (second read must be served by Redis)
    code, body = http(base, "GET", "/notes")
    check("second GET /notes is served from cache",
          code == 200 and (body or {}).get("source") == "cache", f"source={(body or {}).get('source')}")

    # 5. Persistence across a Postgres restart
    if args.quick:
        print("[SKIP] data survives a Postgres restart (--quick)")
    else:
        restarted = compose("restart", "postgres")
        came_back = restarted.returncode == 0 and wait_healthy(base)
        code, body = http(base, "GET", "/notes")
        texts = [n.get("text") for n in (body or {}).get("notes", [])]
        check("data survives a Postgres restart", came_back and marker in texts,
              restarted.stderr.strip()[:120] if not came_back else "note missing")

    # 6. No dependency errors in app logs since verification started
    logs = compose("logs", "--no-color", "--since", start, "app")
    bad = sorted({m for m in ERROR_MARKERS if m in logs.stdout}) if logs.returncode == 0 else ["could not read logs"]
    check("no dependency errors in app logs during verification", not bad, ", ".join(bad))

    passed, total = sum(results), len(results)
    print(f"\n{passed}/{total} checks passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()

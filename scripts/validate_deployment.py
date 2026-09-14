"""Validate a running SIRALOOM deployment without exposing credentials."""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def fetch(url: str) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"body": body[:500]}
        return exc.code, payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url", help="SIRALOOM API base URL, e.g. https://api.example.org")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    checks = {}
    for path in ("/api/v1/health", "/api/v1/ready"):
        status, payload = fetch(base + path)
        checks[path] = {"http_status": status, "payload": payload}

    health_ok = checks["/api/v1/health"]["http_status"] == 200
    ready_payload = checks["/api/v1/ready"]["payload"]
    ready_ok = checks["/api/v1/ready"]["http_status"] == 200 and ready_payload.get("status") == "ok"
    result = {"status": "PASS" if health_ok and ready_ok else "FAIL", "checks": checks}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())

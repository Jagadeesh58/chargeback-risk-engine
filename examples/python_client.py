"""Example Python client for Chargeback Risk Engine API."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

DEFAULT_API_URL = "http://localhost:8000"
DEFAULT_API_KEY = "dev-secret-key-at-least-32-chars-long"


def submit_dispute(
    payload: dict[str, Any],
    api_url: str = DEFAULT_API_URL,
    api_key: str = DEFAULT_API_KEY,
) -> dict[str, Any]:
    """Submit a chargeback dispute payload to the engine and return the decision packet."""
    url = f"{api_url.rstrip('/')}/decision"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        raise RuntimeError(f"HTTP {e.code}: {err_body}") from e


if __name__ == "__main__":
    with open("examples/request_verified.json", "r", encoding="utf-8") as f:
        dispute_data = json.load(f)

    print("Submitting verified dispute payload...")
    result = submit_dispute(dispute_data)
    print(f"Dispute ID: {result.get('dispute_id')}")
    print(f"Action:     {result.get('action')}")
    print(f"Reason:     {result.get('reason')}")
    print(f"Win Prob:   {result.get('calibrated_win_probability', result.get('win_probability'))}")

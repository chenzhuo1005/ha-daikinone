"""Fetch raw Daikin Skyport responses without running Home Assistant.

Credentials are read from DAIKIN_ONE_EMAIL and DAIKIN_ONE_PASSWORD, or are
requested interactively. Authentication tokens are never written or printed.
"""

import argparse
import getpass
import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_BASE_URL = "https://api.daikinskyport.com"
LOGIN_URL = f"{API_BASE_URL}/users/auth/login"
ENDPOINTS = ("locations", "devices", "deviceData")


def fetch_json(url: str, method: str = "GET", body: dict[str, Any] | None = None, access_token: str | None = None) -> Any:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    request = Request(url, data=json.dumps(body).encode() if body else None, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310 -- fixed HTTPS Daikin endpoint
            return json.loads(response.read().decode())
    except HTTPError as error:
        raise RuntimeError(f"{method} {url} failed: HTTP {error.code}: {error.read().decode()[:500]}") from error
    except URLError as error:
        raise RuntimeError(f"{method} {url} failed: {error.reason}") from error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch raw Daikin Skyport API diagnostics.")
    parser.add_argument(
        "--output",
        type=Path,
        help="Output JSON path (default: diagnostics/daikin_raw_<UTC timestamp>.json).",
    )
    parser.add_argument("--no-locations", action="store_true", help="Skip /locations and /devices requests.")
    return parser.parse_args()


def summarize_device_data(device_data: list[dict[str, Any]]) -> dict[str, Any]:
    """Print metadata useful for comparing reported fields without changing raw data."""
    fields: Counter[str] = Counter()
    for device in device_data:
        fields.update(device.get("data", {}).keys())
    return {
        "device_count": len(device_data),
        "devices": [
            {
                "id": device.get("id"),
                "name": device.get("name"),
                "model": device.get("model"),
                "online": device.get("online"),
                "field_count": len(device.get("data", {})),
            }
            for device in device_data
        ],
        "fields": dict(sorted(fields.items())),
    }


def main() -> None:
    args = parse_args()
    email = os.getenv("DAIKIN_ONE_EMAIL") or input("Daikin account email: ").strip()
    password = os.getenv("DAIKIN_ONE_PASSWORD") or getpass.getpass("Daikin account password: ")
    if not email or not password:
        raise SystemExit("Both email and password are required.")

    auth = fetch_json(LOGIN_URL, method="POST", body={"email": email, "password": password})
    access_token = auth.get("accessToken")
    if not access_token:
        raise RuntimeError("Login succeeded but did not return an access token.")

    responses: dict[str, Any] = {}
    for endpoint in ENDPOINTS:
        if args.no_locations and endpoint in {"locations", "devices"}:
            continue
        responses[endpoint] = fetch_json(f"{API_BASE_URL}/{endpoint}", access_token=access_token)

    device_data = responses.get("deviceData", [])
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = args.output or Path("diagnostics") / f"daikin_raw_{timestamp}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    diagnostic = {
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "api_base_url": API_BASE_URL,
        "responses": responses,
        "summary": summarize_device_data(device_data),
    }
    output.write_text(json.dumps(diagnostic, indent=2, sort_keys=True), encoding="utf-8")

    print(f"Wrote raw diagnostic response to: {output.resolve()}")
    print(json.dumps(diagnostic["summary"], indent=2))
    print("Authentication tokens and password were not written to the file.")


if __name__ == "__main__":
    main()

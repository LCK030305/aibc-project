"""CLOAK FTA debug capture — produces a self-contained log for support.

Run:
    python cloak_debug.py

Output:
    cloak_debug.log  (safe to attach to cloak@tech.gov.sg)

What this captures (so the CLOAK team can diagnose 403s without code):
    - Local + UTC time (date-skew check)
    - Public key length + last 4 chars
    - Private key length (value never printed)
    - Canonical request (verbatim — this is what the signature is over)
    - String to sign
    - Final signature
    - Request URL, method, headers (Authorization masked)
    - Request body (JSON, pretty-printed)
    - HTTP status code
    - Response headers
    - Response body (verbatim)

This file does NOT change pii_filter.py — it reuses its signing function.
"""

from __future__ import annotations

import datetime
import io
import json
import sys

import requests

import pii_filter as pf
from llm import get_secret


def mask_key(key: str) -> str:
    if not key:
        return "(empty)"
    if len(key) <= 4:
        return "*" * len(key)
    return f"{'*' * (len(key) - 4)}{key[-4:]}  (length={len(key)})"


def mask_auth_header(value: str) -> str:
    # Authorization header carries the signature; safe to show.
    # But we hide the Credential value (public key) prefix beyond last 4.
    parts = value.split(",")
    masked = []
    for p in parts:
        if p.strip().startswith("CLOAK-AUTH Credential="):
            cred = p.split("=", 1)[1]
            masked.append(f"CLOAK-AUTH Credential={mask_key(cred)}")
        else:
            masked.append(p)
    return ",".join(masked)


def main() -> int:
    # Force UTF-8 stdout for Windows.
    try:
        if (
            hasattr(sys.stdout, "isatty")
            and sys.stdout.isatty()
            and sys.stdout.encoding
            and sys.stdout.encoding.lower() != "utf-8"
        ):
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding="utf-8", line_buffering=True,
            )
    except (AttributeError, OSError, ValueError):
        pass

    # Tee stdout to both terminal and log file.
    log_path = "cloak_debug.log"
    log_file = open(log_path, "w", encoding="utf-8")

    class Tee:
        def __init__(self, *streams):
            self.streams = streams

        def write(self, data):
            for s in self.streams:
                s.write(data)
                s.flush()

        def flush(self):
            for s in self.streams:
                s.flush()

    sys.stdout = Tee(sys.__stdout__, log_file)

    print("=" * 78)
    print("CLOAK FTA debug capture")
    print("=" * 78)

    # ----- Time / clock checks (date-skew is a common 403 cause) -----------
    now_local = datetime.datetime.now()
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    today_utc = datetime.date.today()
    print(f"\nLocal time      : {now_local.isoformat()}")
    print(f"UTC time        : {now_utc.isoformat()}")
    print(f"UTC date stamp  : {today_utc.strftime('%Y%m%d')}  "
          f"(used for date_key derivation)")

    # ----- Key presence ---------------------------------------------------
    public_key = get_secret("CLOAK_PUBLIC_KEY")
    private_key = get_secret("CLOAK_PRIVATE_KEY")
    print(f"\nPublic key      : {mask_key(public_key)}")
    print(f"Private key     : (length={len(private_key) if private_key else 0}; "
          f"value never printed)")
    if not public_key or not private_key:
        print("\nABORT: keys missing.")
        return 1

    # ----- Minimal test payload -------------------------------------------
    test_text = "John Tan lives at Block 100 Ang Mo Kio."
    payload = {
        "text": test_text,
        "language": "en",
        "entities": pf.DEFAULT_ENTITIES,
        "score_threshold": 0.3,
        "anonymizers": pf.DEFAULT_ANONYMIZERS,
    }

    url = f"{pf.CLOAK_BASE_URL}/transform"
    path, query_params = pf.extract_url_info(url)
    signed_headers = {"Content-Type": "application/json"}

    print(f"\nURL             : {url}")
    print(f"Path            : {path}")
    print(f"Query params    : {query_params}")
    print(f"Service         : {pf.CLOAK_SERVICE}")

    # ----- Replicate the signing flow with intermediate prints ------------
    import hashlib
    import urllib.parse

    canonical_uri = urllib.parse.quote(path, safe="/")
    canonical_querystring = "&".join(
        f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}"
        for k, v in sorted(query_params.items())
    )
    sorted_headers = sorted(signed_headers.items())
    canonical_headers = "".join(
        f"{k.lower()}:{v.strip()}\n" for k, v in sorted_headers
    )
    signed_headers_string = ";".join(k.lower() for k, _ in sorted_headers)
    # Compact JSON (no whitespace) — must match the server's payload hash.
    payload_str = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    payload_hash = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

    canonical_request = (
        f"POST\n"
        f"{canonical_uri}\n"
        f"{canonical_querystring}\n"
        f"{canonical_headers}\n"
        f"{signed_headers_string}\n"
        f"{payload_hash}"
    )

    print("\n--- Canonical request ---------------------------------------")
    print(canonical_request)
    print("--- end canonical request -----------------------------------")

    formatted_date = today_utc.strftime("%Y%m%d") + "T000000Z"
    cr_hash = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    string_to_sign = (
        f"CLOAK-AUTH\n"
        f"{formatted_date}\n"
        f"{cr_hash}"
    )
    print("\n--- String to sign ------------------------------------------")
    print(string_to_sign)
    print("--- end string to sign --------------------------------------")

    signature = pf.generate_signature(
        "POST", path, query_params, signed_headers,
        payload, private_key, pf.CLOAK_SERVICE,
    )
    print(f"\nFinal signature : {signature}")

    authorization = (
        f"CLOAK-AUTH Credential={public_key},"
        f"SignedHeaders=content-type,Signature={signature}"
    )
    request_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": authorization,
        "x-cloak-service": pf.CLOAK_SERVICE,
    }

    print("\n--- Request headers (Authorization masked) ------------------")
    for k, v in request_headers.items():
        if k == "Authorization":
            print(f"  {k}: {mask_auth_header(v)}")
        else:
            print(f"  {k}: {v}")

    print("\n--- Request body (JSON, sorted keys) ------------------------")
    print(payload_str)
    print("--- end request body ----------------------------------------")

    # ----- Send -----------------------------------------------------------
    print("\nSending POST ...")
    try:
        response = requests.post(
            url, headers=request_headers, json=payload,
            timeout=pf.CLOAK_TIMEOUT_SEC,
        )
    except Exception as exc:
        print(f"\nTRANSPORT ERROR: {type(exc).__name__}: {exc}")
        return 2

    # ----- Response capture ----------------------------------------------
    print(f"\nHTTP status     : {response.status_code} {response.reason}")
    print("\n--- Response headers ----------------------------------------")
    for k, v in response.headers.items():
        print(f"  {k}: {v}")
    print("\n--- Response body (verbatim) --------------------------------")
    print(response.text)
    print("--- end response body ---------------------------------------")

    print("\n" + "=" * 78)
    print(f"Log written to: {log_path}")
    print("=" * 78)
    log_file.close()
    return 0 if response.status_code < 400 else 3


if __name__ == "__main__":
    raise SystemExit(main())

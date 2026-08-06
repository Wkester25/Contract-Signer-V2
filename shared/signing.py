"""Shared HMAC signing/verification for the internal webhook call between
Program 1 (Stripe relay) and Program 2 (contract merge/print service).

Deliberately mirrors the scheme Stripe itself uses for webhook signatures:

    signed_payload = f"{timestamp}.{raw_body}"
    signature = hmac_sha256(shared_secret, signed_payload)
    header = f"t={timestamp},v1={signature}"

Including the timestamp in the signed material and rejecting anything
outside `tolerance_seconds` prevents a captured request from being replayed
later (e.g. to re-print/re-store an old contract).

Both programs must share the same `RELAY_SHARED_SECRET` (set via env var,
not committed to source control).
"""
import hashlib
import hmac
import time


class SignatureVerificationError(Exception):
    """Raised when an incoming request's signature can't be verified."""


def sign_payload(body: bytes, secret: str, timestamp: int | None = None) -> str:
    if timestamp is None:
        timestamp = int(time.time())
    signed_payload = f"{timestamp}.".encode() + body
    signature = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


def verify_signature(body: bytes, header: str, secret: str, tolerance_seconds: int = 300) -> None:
    """Raises SignatureVerificationError if the header is missing, malformed,
    expired, or doesn't match the body."""
    if not header:
        raise SignatureVerificationError("Missing X-Relay-Signature header")

    try:
        parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    except ValueError:
        raise SignatureVerificationError("Malformed signature header") from None

    timestamp_str, signature = parts.get("t"), parts.get("v1")
    if not timestamp_str or not signature:
        raise SignatureVerificationError("Malformed signature header")

    try:
        timestamp = int(timestamp_str)
    except ValueError:
        raise SignatureVerificationError("Malformed timestamp in signature header") from None

    if abs(time.time() - timestamp) > tolerance_seconds:
        raise SignatureVerificationError("Signature timestamp outside tolerance (possible replay)")

    signed_payload = f"{timestamp}.".encode() + body
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise SignatureVerificationError("Signature does not match body")

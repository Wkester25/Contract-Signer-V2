import os


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Required environment variable {name} is not set")
    return value


class Config:
    # Must match Program 1's RELAY_SHARED_SECRET exactly.
    RELAY_SHARED_SECRET = _require("RELAY_SHARED_SECRET")

    # How far a request's timestamp may drift from "now" before it's
    # rejected as a possible replay.
    SIGNATURE_TOLERANCE_SECONDS = int(os.environ.get("SIGNATURE_TOLERANCE_SECONDS", "300"))

    # STUB-ONLY: where this placeholder receiver drops what it got, so you
    # can eyeball that account number / signature / contract all arrived
    # intact. Real merge/PDF/hash/DB/print logic replaces this in later steps.
    RECEIVED_DUMP_DIR = os.environ.get("RECEIVED_DUMP_DIR", "/tmp/program2_received")

    PORT = int(os.environ.get("PORT", "8443"))

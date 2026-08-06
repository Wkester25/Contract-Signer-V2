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

    # --- Signature placement on the contract ---
    # All coordinates are in PDF points (72/inch), origin at the bottom-left
    # of the page - standard PDF/reportlab convention.
    # Page number is 1-indexed; -1 means "last page".
    SIGNATURE_PAGE_NUMBER = int(os.environ.get("SIGNATURE_PAGE_NUMBER", "-1"))
    SIGNATURE_X = float(os.environ.get("SIGNATURE_X", "72"))  # 1 inch from left
    SIGNATURE_Y = float(os.environ.get("SIGNATURE_Y", "110"))  # ~1.5 inch from bottom
    # The signature image is scaled to fit inside this box, preserving its
    # aspect ratio, anchored at (SIGNATURE_X, SIGNATURE_Y).
    SIGNATURE_MAX_WIDTH = float(os.environ.get("SIGNATURE_MAX_WIDTH", "220"))
    SIGNATURE_MAX_HEIGHT = float(os.environ.get("SIGNATURE_MAX_HEIGHT", "70"))

    # --- Account number / saved-at stamp ---
    STAMP_PAGE_NUMBER = int(os.environ.get("STAMP_PAGE_NUMBER", "-1"))
    STAMP_X = float(os.environ.get("STAMP_X", "72"))
    STAMP_Y = float(os.environ.get("STAMP_Y", "70"))
    STAMP_FONT_NAME = os.environ.get("STAMP_FONT_NAME", "Helvetica")
    STAMP_FONT_SIZE = float(os.environ.get("STAMP_FONT_SIZE", "9"))
    # {account_number} and {saved_at} are substituted in.
    STAMP_TEXT_TEMPLATE = os.environ.get(
        "STAMP_TEXT_TEMPLATE", "Account: {account_number}    Signed: {saved_at}"
    )
    STAMP_DATETIME_FORMAT = os.environ.get("STAMP_DATETIME_FORMAT", "%Y-%m-%d %H:%M:%S UTC")

    PORT = int(os.environ.get("PORT", "8443"))

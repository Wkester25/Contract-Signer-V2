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

    # DEBUG-ONLY: where the receiver additionally drops the raw inputs it got
    # (signature.svg, the blank contract, a meta.txt) for troubleshooting a
    # bad merge without re-triggering a real signature capture. Not the real
    # save location - see OUTPUT_DIR below for that.
    RECEIVED_DUMP_DIR = os.environ.get("RECEIVED_DUMP_DIR", "/tmp/program2_received")

    # --- Where finished, signed contracts are actually saved ---
    OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "/var/contract-pipeline/signed")
    # {account_number} and {saved_at} are substituted in. saved_at here uses
    # FILENAME_DATETIME_FORMAT - deliberately a *different* format from
    # STAMP_DATETIME_FORMAT above, since filenames can't safely contain the
    # colons/spaces that make a good on-page timestamp.
    FILENAME_TEMPLATE = os.environ.get("FILENAME_TEMPLATE", "{account_number}_{saved_at}.pdf")
    FILENAME_DATETIME_FORMAT = os.environ.get("FILENAME_DATETIME_FORMAT", "%Y%m%d-%H%M%S")

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

    # --- PostgreSQL: where the contract hash record is stored ---
    # Either set DATABASE_URL as a single connection string, e.g.
    #   postgresql://user:password@host:5432/dbname?sslmode=require
    # or leave it unset and configure the individual POSTGRES_* values below.
    # DATABASE_URL wins if both are set.
    DATABASE_URL = os.environ.get("DATABASE_URL")

    POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
    POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
    POSTGRES_DB = os.environ.get("POSTGRES_DB", "contract_pipeline")
    POSTGRES_USER = os.environ.get("POSTGRES_USER", "contract_pipeline")
    POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "")
    # require/verify-full recommended once you have real certs in production;
    # prefer is a safe default that still works against a plain local/dev DB.
    POSTGRES_SSLMODE = os.environ.get("POSTGRES_SSLMODE", "prefer")
    POSTGRES_CONNECT_TIMEOUT_SECONDS = int(os.environ.get("POSTGRES_CONNECT_TIMEOUT_SECONDS", "10"))
    POSTGRES_APPLICATION_NAME = os.environ.get(
        "POSTGRES_APPLICATION_NAME", "contract-signing-pipeline"
    )
    # Schema/table names are configurable too - identifiers are safely quoted
    # via psycopg2.sql wherever they're used, so any valid Postgres
    # identifier works without risking SQL injection through config.
    POSTGRES_SCHEMA = os.environ.get("POSTGRES_SCHEMA", "public")
    POSTGRES_TABLE = os.environ.get("POSTGRES_TABLE", "signed_contracts")

    PORT = int(os.environ.get("PORT", "8443"))

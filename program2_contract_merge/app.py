"""
Program 2 - contract merge service.

Receives the signed relay call from Program 1, verifies it, merges the
signature SVG + an account-number/saved-at stamp onto the blank contract,
saves the finished PDF under a filename derived from the account number and
the save timestamp, hashes it, records that hash in Postgres, and prints it.
"""
import base64
import hashlib
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, request, jsonify

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # for `shared`
from shared.signing import verify_signature, SignatureVerificationError  # noqa: E402

from config import Config  # noqa: E402
from contract_merge import merge_signature_and_stamp, ContractMergeError, Placement  # noqa: E402
from storage import build_output_path, save_contract, StorageError  # noqa: E402
from printing import print_contract, PrintError  # noqa: E402
import db  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("program2")

app = Flask(__name__)

try:
    with db.get_connection() as _conn:
        db.ensure_schema(_conn)
    log.info("Postgres schema ready (%s.%s)", Config.POSTGRES_SCHEMA, Config.POSTGRES_TABLE)
except db.DatabaseError as exc:
    # Don't crash the app on startup - /healthz should still respond, and
    # each webhook request will surface the same error loudly if the
    # database is genuinely unreachable (rather than just starting slow).
    log.error("Could not ensure Postgres schema at startup: %s", exc)


@app.route("/webhook/contract", methods=["POST"])
def receive_contract():
    body = request.get_data()
    sig_header = request.headers.get("X-Relay-Signature", "")

    try:
        verify_signature(body, sig_header, Config.RELAY_SHARED_SECRET, Config.SIGNATURE_TOLERANCE_SECONDS)
    except SignatureVerificationError as exc:
        log.warning("Rejected request: %s", exc)
        return jsonify(error=str(exc)), 401

    data = request.get_json(force=True)
    account_number = data["account_number"]
    captured_at = data["captured_at"]
    signature_svg_bytes = base64.b64decode(data["signature_svg_base64"])
    contract_bytes = base64.b64decode(data["contract_template_base64"])
    contract_filename = data["contract_template_filename"]

    # "The time and date it was saved" - i.e. now, when Program 2 processes
    # it, not when Stripe captured the signature (that's `captured_at`).
    saved_at = datetime.now(timezone.utc)
    saved_at_text = saved_at.strftime(Config.STAMP_DATETIME_FORMAT)

    try:
        merged_pdf_bytes = merge_signature_and_stamp(
            contract_bytes=contract_bytes,
            signature_svg_bytes=signature_svg_bytes,
            account_number=account_number,
            saved_at_text=saved_at_text,
            signature_placement=Placement(
                page_number=Config.SIGNATURE_PAGE_NUMBER,
                x=Config.SIGNATURE_X,
                y=Config.SIGNATURE_Y,
            ),
            signature_max_width=Config.SIGNATURE_MAX_WIDTH,
            signature_max_height=Config.SIGNATURE_MAX_HEIGHT,
            stamp_placement=Placement(
                page_number=Config.STAMP_PAGE_NUMBER,
                x=Config.STAMP_X,
                y=Config.STAMP_Y,
            ),
            stamp_text_template=Config.STAMP_TEXT_TEMPLATE,
            stamp_font_name=Config.STAMP_FONT_NAME,
            stamp_font_size=Config.STAMP_FONT_SIZE,
        )
    except ContractMergeError as exc:
        log.error("Failed to merge contract for account %s: %s", account_number, exc)
        # 200 - a malformed SVG/contract for this specific event won't fix
        # itself on retry, so don't have Program 1/Stripe hammer it.
        return jsonify(error=str(exc)), 200

    try:
        output_path = build_output_path(
            output_dir=Path(Config.OUTPUT_DIR),
            account_number=account_number,
            saved_at=saved_at,
            filename_template=Config.FILENAME_TEMPLATE,
            filename_datetime_format=Config.FILENAME_DATETIME_FORMAT,
        )
        save_contract(merged_pdf_bytes, output_path)
    except StorageError as exc:
        log.error("Refused to save contract for account %s: %s", account_number, exc)
        # 200 - an unsafe/invalid account number won't become safe on retry.
        return jsonify(error=str(exc)), 200
    except OSError as exc:
        log.error("Failed to write contract for account %s to disk: %s", account_number, exc)
        # 500 - disk/permission problem is worth Stripe/Program 1 retrying.
        return jsonify(error="failed to save contract"), 500

    # Hash what's actually on disk (not the in-memory bytes) - a faithful
    # hash of "that contract" as stored, catching any write-path corruption
    # too, however unlikely.
    sha256_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()

    try:
        captured_at_dt = datetime.fromisoformat(captured_at) if captured_at else None
        with db.get_connection() as conn:
            row_id = db.insert_contract_record(
                conn,
                account_number=account_number,
                file_path=str(output_path),
                sha256_hash=sha256_hash,
                captured_at=captured_at_dt,
                saved_at=saved_at,
            )
    except db.DatabaseError as exc:
        log.error("Failed to record hash for account %s: %s", account_number, exc)
        # 500 - the PDF is already safely on disk at this point; this is a
        # DB connectivity problem worth retrying. Note a retry re-runs the
        # whole flow from Program 1, so it will produce a second saved PDF
        # (collision-safe filename) and a second hash row rather than
        # resuming this one - see README "Known limitations".
        return jsonify(error="failed to record contract hash"), 500

    # Printing is last and, unlike the steps above, doesn't get to fail the
    # whole webhook: the contract is already safely saved + hashed, which is
    # the part that can't be redone without a fresh signature. Returning 500
    # here would make Stripe/Program 1 retry the *entire* flow just to retry
    # printing, producing a duplicate saved file and a duplicate DB row (see
    # README "Known limitations"). So a print failure is logged loudly for
    # manual follow-up / reprint (see scripts/reprint.py) instead.
    if Config.PRINT_ENABLED:
        try:
            print_detail = print_contract(
                path=output_path,
                printer_name=Config.PRINTER_NAME,
                copies=Config.PRINT_COPIES,
                options=Config.PRINT_OPTIONS,
                timeout_seconds=Config.PRINT_TIMEOUT_SECONDS,
            )
            print_status = "submitted"
        except PrintError as exc:
            log.error(
                "Failed to print contract for account %s (saved+recorded, NOT printed - "
                "reprint manually): %s",
                account_number,
                exc,
            )
            print_status = "failed"
            print_detail = str(exc)
    else:
        print_status = "disabled"
        print_detail = None

    # DEBUG: also dump the raw inputs for troubleshooting a bad merge
    # without re-triggering a real signature capture. Not the real save.
    debug_dir = Path(Config.RECEIVED_DUMP_DIR) / account_number
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / "signature.svg").write_bytes(signature_svg_bytes)
    (debug_dir / contract_filename).write_bytes(contract_bytes)
    (debug_dir / "meta.txt").write_text(
        f"account_number={account_number}\ncaptured_at={captured_at}\n"
        f"saved_at={saved_at.isoformat()}\nsaved_path={output_path}\n"
        f"sha256={sha256_hash}\ndb_id={row_id}\n"
        f"print_status={print_status}\nprint_detail={print_detail}\n",
        encoding="utf-8",
    )

    log.info(
        "Saved + recorded signed contract for account %s (captured %s, saved %s) -> %s "
        "(sha256=%s, db_id=%s, print_status=%s)",
        account_number,
        captured_at,
        saved_at_text,
        output_path,
        sha256_hash,
        row_id,
        print_status,
    )
    return (
        jsonify(
            status="saved",
            account_number=account_number,
            path=str(output_path),
            sha256=sha256_hash,
            db_id=row_id,
            print_status=print_status,
            print_detail=print_detail,
        ),
        200,
    )


@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify(status="ok"), 200


if __name__ == "__main__":
    # NOTE: use a real TLS termination (nginx/caddy in front, or ssl_context
    # here) in production - PROGRAM2_URL in Program 1's config is https://.
    app.run(host="0.0.0.0", port=Config.PORT)

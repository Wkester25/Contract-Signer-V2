"""
Program 2 - contract merge service.

Receives the signed relay call from Program 1, verifies it, merges the
signature SVG + an account-number/saved-at stamp onto the blank contract,
and saves the finished PDF under a filename derived from the account
number and the save timestamp.

Hashing the saved PDF into Postgres and printing it come next.
"""
import base64
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("program2")

app = Flask(__name__)


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

    # DEBUG: also dump the raw inputs for troubleshooting a bad merge
    # without re-triggering a real signature capture. Not the real save.
    debug_dir = Path(Config.RECEIVED_DUMP_DIR) / account_number
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / "signature.svg").write_bytes(signature_svg_bytes)
    (debug_dir / contract_filename).write_bytes(contract_bytes)
    (debug_dir / "meta.txt").write_text(
        f"account_number={account_number}\ncaptured_at={captured_at}\n"
        f"saved_at={saved_at.isoformat()}\nsaved_path={output_path}\n",
        encoding="utf-8",
    )

    log.info(
        "Saved signed contract for account %s (captured %s, saved %s) -> %s",
        account_number,
        captured_at,
        saved_at_text,
        output_path,
    )
    return jsonify(status="saved", account_number=account_number, path=str(output_path)), 200


@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify(status="ok"), 200


if __name__ == "__main__":
    # NOTE: use a real TLS termination (nginx/caddy in front, or ssl_context
    # here) in production - PROGRAM2_URL in Program 1's config is https://.
    app.run(host="0.0.0.0", port=Config.PORT)

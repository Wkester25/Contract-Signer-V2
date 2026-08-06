"""
Program 2 - contract merge service.

Receives the signed relay call from Program 1, verifies it, and merges the
signature SVG + an account-number/saved-at stamp onto the blank contract to
produce a finished PDF.

Still stub-level beyond this point: the finished PDF is written under
RECEIVED_DUMP_DIR for inspection rather than saved to its real destination.
Stage 3 replaces that with the actual account-number-named save path; hash
+ Postgres storage and printing come after that.
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

    # STUB: dump inputs + the merged PDF for inspection. Stage 3 replaces
    # this with saving to the real configured output location.
    out_dir = Path(Config.RECEIVED_DUMP_DIR) / account_number
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "signature.svg").write_bytes(signature_svg_bytes)
    (out_dir / contract_filename).write_bytes(contract_bytes)
    (out_dir / "merged_preview.pdf").write_bytes(merged_pdf_bytes)
    (out_dir / "meta.txt").write_text(
        f"account_number={account_number}\ncaptured_at={captured_at}\nsaved_at={saved_at.isoformat()}\n",
        encoding="utf-8",
    )

    log.info(
        "Merged contract for account %s (captured %s, saved %s) - wrote %s",
        account_number,
        captured_at,
        saved_at_text,
        out_dir,
    )
    return jsonify(status="merged", account_number=account_number), 200


@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify(status="ok"), 200


if __name__ == "__main__":
    # NOTE: use a real TLS termination (nginx/caddy in front, or ssl_context
    # here) in production - PROGRAM2_URL in Program 1's config is https://.
    app.run(host="0.0.0.0", port=Config.PORT)

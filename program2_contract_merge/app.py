"""
Program 2 - STUB receiver.

This is a placeholder for the machine that will eventually do the real
work (merge signature onto contract, render PDF, hash, store in Postgres,
print). Right now it only:

  1. Verifies the signed request actually came from Program 1.
  2. Decodes the account number, signature SVG, and blank contract.
  3. Writes them to disk under RECEIVED_DUMP_DIR so you can confirm the
     handoff from Program 1 works end-to-end.

The merge/PDF/hash/DB/print logic will replace step 3 in the next pass.
"""
import base64
import logging
import sys
from pathlib import Path

from flask import Flask, request, jsonify

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # for `shared`
from shared.signing import verify_signature, SignatureVerificationError  # noqa: E402

from config import Config  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("program2-stub")

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

    out_dir = Path(Config.RECEIVED_DUMP_DIR) / account_number
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "signature.svg").write_bytes(signature_svg_bytes)
    (out_dir / contract_filename).write_bytes(contract_bytes)
    (out_dir / "meta.txt").write_text(
        f"account_number={account_number}\ncaptured_at={captured_at}\n", encoding="utf-8"
    )

    log.info(
        "Received signature for account %s (captured %s) - wrote %s",
        account_number,
        captured_at,
        out_dir,
    )
    return jsonify(status="received", account_number=account_number), 200


@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify(status="ok"), 200


if __name__ == "__main__":
    # NOTE: use a real TLS termination (nginx/caddy in front, or ssl_context
    # here) in production - PROGRAM2_URL in Program 1's config is https://.
    app.run(host="0.0.0.0", port=Config.PORT)

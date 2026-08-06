"""
Program 1 - Stripe Terminal signature relay.

Runs on (or near) the payment terminal machine. Listens for the Stripe
webhook fired once a customer's signature has been captured on the
terminal, pulls the blank contract template off local disk, and forwards
{account_number, signature_svg, blank_contract, captured_at} to Program 2
(on a different machine) over a signed internal webhook call.

Program 2 is responsible for the actual merge/PDF/hash/DB/print work -
this program's only job is: verify Stripe -> extract -> relay.

The webhook only tells us a File ID for the signature (Stripe stores
collect_inputs signature images as an SVG File, not inline data), so we
make a follow-up authenticated call to Stripe's Files API to download it.
Stripe only retains these files for 7 days, so that download happens
synchronously inside the webhook handler, right away.
"""
import base64
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
import stripe
from flask import Flask, request, jsonify

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # for `shared`
from shared.signing import sign_payload  # noqa: E402

from config import Config  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("program1")

app = Flask(__name__)

stripe.api_key = Config.STRIPE_API_KEY
if Config.STRIPE_API_BASE:
    stripe.api_base = Config.STRIPE_API_BASE  # only set for local testing against a fake server

# terminal.reader.action_succeeded fires for ANY successful reader action
# (payment collection, collect_inputs, etc.), not just signature capture -
# so we still have to check action.type == "collect_inputs" below.
SIGNATURE_SUCCESS_EVENT_TYPE = "terminal.reader.action_succeeded"
SIGNATURE_FAILURE_EVENT_TYPE = "terminal.reader.action_failed"
COLLECT_INPUTS_ACTION_TYPE = "collect_inputs"


def _get_path(obj, dotted_path: str):
    """Walk a dotted path like 'a.b.0.c' through nested dicts/lists."""
    current = obj
    for part in dotted_path.split("."):
        if isinstance(current, list):
            current = current[int(part)]
        else:
            current = current[part]
    return current


def extract_account_number(event_object: dict) -> str:
    try:
        value = _get_path(event_object, Config.ACCOUNT_NUMBER_PATH)
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(
            f"Could not find account number at '{Config.ACCOUNT_NUMBER_PATH}' in event payload"
        ) from exc
    if not value:
        raise ValueError("Account number field was present but empty")
    return str(value)


def extract_signature_file_id(event_object: dict) -> str:
    """Find the signature input's Stripe File ID inside
    action.collect_inputs.inputs. Looks it up by `type == "signature"`
    rather than assuming a fixed index, in case the collect_inputs action
    requested other inputs (text, selection, ...) alongside the signature.
    """
    try:
        inputs = event_object["action"]["collect_inputs"]["inputs"]
    except (KeyError, TypeError) as exc:
        raise ValueError("Event payload has no action.collect_inputs.inputs") from exc

    for item in inputs:
        if item.get("type") == "signature":
            file_id = item.get("signature", {}).get("value")
            if file_id:
                return file_id
    raise ValueError("No signature input found in action.collect_inputs.inputs")


def download_signature_svg(file_id: str) -> bytes:
    """Retrieve the signature File object, then download its actual SVG
    bytes from the File's url. File downloads use the same secret-key auth
    as any other Stripe API call (HTTP basic auth, secret key as username,
    blank password) - it's not a public URL.
    """
    file_obj = stripe.File.retrieve(file_id)
    url = getattr(file_obj, "url", None)
    if not url:
        raise ValueError(f"Stripe file {file_id} has no downloadable url")

    response = requests.get(
        url, auth=(Config.STRIPE_API_KEY, ""), timeout=Config.REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    return response.content


def load_blank_contract() -> bytes:
    path = Path(Config.CONTRACT_TEMPLATE_PATH)
    if not path.is_file():
        raise FileNotFoundError(f"Blank contract template not found at {path}")
    return path.read_bytes()


def forward_to_program2(account_number: str, signature_svg_bytes: bytes, contract_bytes: bytes) -> None:
    payload = {
        "account_number": account_number,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "signature_svg_base64": base64.b64encode(signature_svg_bytes).decode("ascii"),
        "contract_template_base64": base64.b64encode(contract_bytes).decode("ascii"),
        "contract_template_filename": Path(Config.CONTRACT_TEMPLATE_PATH).name,
    }
    body = json.dumps(payload).encode("utf-8")
    signature_header = sign_payload(body, Config.RELAY_SHARED_SECRET)

    response = requests.post(
        Config.PROGRAM2_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Relay-Signature": signature_header,
        },
        timeout=Config.REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    log.info(
        "Forwarded signature for account %s to Program 2 (status %s)",
        account_number,
        response.status_code,
    )


@app.route("/webhook/stripe", methods=["POST"])
def stripe_webhook():
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, Config.STRIPE_WEBHOOK_SECRET)
    except ValueError:
        log.warning("Invalid Stripe webhook payload (not valid JSON)")
        return jsonify(error="invalid payload"), 400
    except stripe.error.SignatureVerificationError:
        log.warning("Invalid Stripe webhook signature")
        return jsonify(error="invalid signature"), 400

    event_type = event["type"]
    event_object = event["data"]["object"]

    if event_type == SIGNATURE_FAILURE_EVENT_TYPE:
        action = event_object.get("action", {})
        log.info(
            "Reader action failed for reader %s (event %s): status=%s failure_code=%s failure_message=%s",
            event_object.get("id"),
            event["id"],
            action.get("status"),
            action.get("failure_code"),
            action.get("failure_message"),
        )
        # Customer canceled, or the reader sat untouched for 2 minutes and
        # timed out - no signature to forward. Acknowledge so Stripe doesn't retry.
        return jsonify(status="ignored", type=event_type), 200

    if event_type != SIGNATURE_SUCCESS_EVENT_TYPE:
        # Not an event we care about - acknowledge so Stripe doesn't retry.
        return jsonify(status="ignored", type=event_type), 200

    action = event_object.get("action", {})
    if action.get("type") != COLLECT_INPUTS_ACTION_TYPE:
        # A different kind of reader action succeeded (e.g. a payment
        # collection) - not a signature event, nothing for us to do.
        return jsonify(status="ignored", type=event_type, action_type=action.get("type")), 200

    try:
        account_number = extract_account_number(event_object)
        file_id = extract_signature_file_id(event_object)
        signature_svg_bytes = download_signature_svg(file_id)
        contract_bytes = load_blank_contract()
    except (ValueError, FileNotFoundError) as exc:
        log.error("Failed to process signature event %s: %s", event["id"], exc)
        # 200 so Stripe doesn't endlessly retry an event we can never process;
        # the failure is logged for follow-up. Consider 500 during initial
        # testing if you'd rather Stripe keep retrying while you fix paths.
        return jsonify(error=str(exc)), 200
    except stripe.error.StripeError as exc:
        log.error("Stripe API error retrieving signature file for event %s: %s", event["id"], exc)
        # 500 so Stripe retries - this is a transient API/network problem,
        # not a bad event, and the file is only available for 7 days.
        return jsonify(error="failed to retrieve signature file"), 500

    try:
        forward_to_program2(account_number, signature_svg_bytes, contract_bytes)
    except requests.RequestException as exc:
        log.error("Failed to forward to Program 2: %s", exc)
        # 500 so Stripe retries delivery - this failure is on our internal
        # network/Program 2, not a problem with the Stripe event itself.
        return jsonify(error="internal forwarding failed"), 500

    return jsonify(status="forwarded", account_number=account_number), 200


@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify(status="ok"), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=Config.PORT)

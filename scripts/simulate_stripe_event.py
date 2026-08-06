"""
Dev-only helper. Builds a fake Stripe `terminal.reader.action_succeeded`
event matching the real collect_inputs signature payload shape (a file ID,
not raw SVG data), signs it the same way Stripe signs real webhooks, and
POSTs it to Program 1's /webhook/stripe endpoint. Lets you smoke-test the
whole relay -> Files API download -> Program 2 chain without real Stripe
Terminal hardware.

Run scripts/fake_stripe_files_server.py first, and point Program 1's
STRIPE_API_BASE at it, so the file-ID-> SVG download step has something to
hit instead of real Stripe.

Usage:
    STRIPE_WEBHOOK_SECRET=whsec_test python3 scripts/simulate_stripe_event.py
"""
import json
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.signing import sign_payload  # noqa: E402

PROGRAM1_URL = os.environ.get("PROGRAM1_URL", "http://localhost:5000/webhook/stripe")
STRIPE_WEBHOOK_SECRET = os.environ["STRIPE_WEBHOOK_SECRET"]
ACCOUNT_NUMBER = os.environ.get("TEST_ACCOUNT_NUMBER", "ACC-00123")
FAKE_FILE_ID = os.environ.get("TEST_FILE_ID", "file_1FakeSignature123")

event = {
    "id": "evt_test_123",
    "type": "terminal.reader.action_succeeded",
    "data": {
        "object": {
            "id": "tmr_test_123",
            "object": "terminal.reader",
            "metadata": {"account_number": ACCOUNT_NUMBER},
            "action": {
                "type": "collect_inputs",
                "status": "succeeded",
                "collect_inputs": {
                    "inputs": [{"type": "signature", "signature": {"value": FAKE_FILE_ID}}]
                },
            },
        }
    },
}

body = json.dumps(event).encode("utf-8")
# Stripe's real header format is "t=<ts>,v1=<sig>" - the same scheme as our
# internal shared.signing, so it can sign this fake event with the Stripe
# secret too.
stripe_signature_header = sign_payload(body, STRIPE_WEBHOOK_SECRET)

response = requests.post(
    PROGRAM1_URL,
    data=body,
    headers={"Content-Type": "application/json", "Stripe-Signature": stripe_signature_header},
    timeout=10,
)
print(response.status_code, response.text)

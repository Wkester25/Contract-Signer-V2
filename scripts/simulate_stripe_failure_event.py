"""
Dev-only helper. Fires a fake `terminal.reader.action_failed` event
(customer canceled, or the reader timed out after 2 minutes) at Program 1,
to confirm it's acknowledged and logged without attempting to forward
anything to Program 2.

Usage:
    STRIPE_WEBHOOK_SECRET=whsec_test python3 scripts/simulate_stripe_failure_event.py
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

event = {
    "id": "evt_test_failed_123",
    "type": "terminal.reader.action_failed",
    "data": {
        "object": {
            "id": "tmr_test_123",
            "object": "terminal.reader",
            "action": {
                "type": "collect_inputs",
                "status": "failed",
                "failure_code": "terminal_reader_timeout",
                "failure_message": "The reader timed out waiting for customer input.",
            },
        }
    },
}

body = json.dumps(event).encode("utf-8")
stripe_signature_header = sign_payload(body, STRIPE_WEBHOOK_SECRET)

response = requests.post(
    PROGRAM1_URL,
    data=body,
    headers={"Content-Type": "application/json", "Stripe-Signature": stripe_signature_header},
    timeout=10,
)
print(response.status_code, response.text)

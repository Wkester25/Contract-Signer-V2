import os


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Required environment variable {name} is not set")
    return value


class Config:
    # --- Stripe ---
    STRIPE_WEBHOOK_SECRET = _require("STRIPE_WEBHOOK_SECRET")
    # Secret key, used to call the Files API and download the signature SVG
    # (the webhook only gives us a file ID, not the image itself).
    STRIPE_API_KEY = _require("STRIPE_API_KEY")
    # Only set this for local testing against a fake Stripe server
    # (see scripts/fake_stripe_files_server.py). Leave unset in production.
    STRIPE_API_BASE = os.environ.get("STRIPE_API_BASE")

    # --- Where to find the account number inside the Stripe event's
    # data.object JSON --- Dot-separated path, e.g. "metadata.account_number"
    # walks obj["metadata"]["account_number"]. The signature file ID's
    # location is fixed by Stripe's collect_inputs schema and doesn't need
    # configuring (see app.py:extract_signature_file_id).
    #
    # IMPORTANT: this default is a placeholder - confirm where your account
    # number actually lives in a real event before going live (see README
    # "Verifying the Stripe event shape"). If you pass account_number as
    # metadata when creating the collect_inputs action, this is where it'll
    # come back.
    ACCOUNT_NUMBER_PATH = os.environ.get("ACCOUNT_NUMBER_PATH", "metadata.account_number")

    # --- Local blank contract template ---
    CONTRACT_TEMPLATE_PATH = os.environ.get(
        "CONTRACT_TEMPLATE_PATH", "/etc/contract-pipeline/blank_contract.pdf"
    )

    # --- Program 2 (contract merge / print machine) ---
    PROGRAM2_URL = _require("PROGRAM2_URL")  # e.g. https://program2.internal:8443/webhook/contract
    RELAY_SHARED_SECRET = _require("RELAY_SHARED_SECRET")
    REQUEST_TIMEOUT_SECONDS = float(os.environ.get("REQUEST_TIMEOUT_SECONDS", "15"))

    PORT = int(os.environ.get("PORT", "5000"))

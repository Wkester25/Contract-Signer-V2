"""
Dev-only helper. Stands in for Stripe's API when testing Program 1's
signature-download step locally, without hitting real Stripe.

Serves the two endpoints Program 1 actually calls:
    GET /v1/files/<file_id>            -> a File object with a `url`
    GET /v1/files/<file_id>/contents   -> the raw (fake) SVG bytes

Point Program 1 at this by setting STRIPE_API_BASE=http://localhost:<port>
in its environment - the stripe-python SDK will send File.retrieve() calls
here instead of to api.stripe.com, and the `url` this returns points back
at this same server for the content download.

Usage:
    python3 scripts/fake_stripe_files_server.py
"""
import os

from flask import Flask, jsonify, request, Response

app = Flask(__name__)
PORT = int(os.environ.get("FAKE_STRIPE_PORT", "9999"))

FAKE_SIGNATURE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="100">'
    '<path d="M10 80 C 40 10, 65 10, 95 80 S 150 150, 180 80" '
    'stroke="black" fill="transparent"/></svg>'
).encode("utf-8")


@app.route("/v1/files/<file_id>", methods=["GET"])
def get_file(file_id):
    base = request.host_url.rstrip("/")
    return jsonify(
        {
            "id": file_id,
            "object": "file",
            "purpose": "terminal_reader_signature",
            "type": "svg",
            "url": f"{base}/v1/files/{file_id}/contents",
        }
    )


@app.route("/v1/files/<file_id>/contents", methods=["GET"])
def get_file_contents(file_id):
    return Response(FAKE_SIGNATURE_SVG, mimetype="image/svg+xml")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)

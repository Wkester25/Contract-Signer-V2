# Contract signing pipeline

Two programs on two machines:

- **Program 1** (`program1_stripe_relay/`) — lives near the payment terminal.
  Listens for the Stripe webhook fired when a signature is captured on the
  terminal, loads the blank contract template from local disk, and forwards
  `{account_number, signature_svg, blank_contract, captured_at}` to Program 2
  over a signed HTTP request.
- **Program 2** (`program2_contract_merge/`) — verifies the signed request,
  merges the signature SVG and an account-number/saved-at stamp onto the
  blank contract (`contract_merge.py`), and saves the finished PDF under a
  filename derived from the account number and save timestamp
  (`storage.py`). Hashing it into Postgres and printing it are still pending.

Both programs share `shared/signing.py`, an HMAC scheme (mirroring Stripe's
own) used to authenticate the Program1 → Program2 call and reject replays.

## Status

- [x] Program 1: Stripe webhook → extract account number + signature file ID →
      download SVG from Files API → relay to Program 2
- [x] Program 1: guards against other reader-action-succeeded events, handles
      action_failed (cancel/timeout) as a no-op
- [x] Program 2: verify signature, confirm account number/SVG/contract arrive intact
- [x] Program 2: merge signature onto contract at a configurable location, render PDF, stamp account number + save timestamp (also written into PDF metadata as `/AccountNumber` / `/SignedAt`)
- [x] Program 2: save signed contract as `<account_number>_<timestamp>.pdf` under a configurable output dir, sanitized against path traversal, written atomically, collision-safe
- [ ] Program 2: hash the saved PDF (SHA-256) and store it in PostgreSQL with account number + timestamp
- [ ] Program 2: print the finished contract via CUPS

## Setup

```bash
cd contract-signing-pipeline
python3 -m venv .venv && source .venv/bin/activate
pip install -r program1_stripe_relay/requirements.txt
pip install -r program2_contract_merge/requirements.txt
```

Copy `program1_stripe_relay/.env.example` to `.env` in that directory and
fill in real values. Program 2 needs `RELAY_SHARED_SECRET` (same value as
Program 1) in its own environment.

## The Stripe event shape

Confirmed: `terminal.reader.action_succeeded` fires once the customer
finishes signing and hits submit. The webhook itself only carries a **file
ID** for the signature (not the image), found by scanning
`data.object.action.collect_inputs.inputs` for the entry with
`type == "signature"` (`extract_signature_file_id()` in app.py — it
searches by type rather than assuming index 0, in case other inputs were
collected on the same screen). Program 1 then makes a follow-up call to
Stripe's Files API (`stripe.File.retrieve()` + an authenticated GET on the
file's `url`) to download the actual SVG bytes.

Two things worth knowing about this event type:

- **The same event type fires for any successful reader action** (payment
  collection, `collect_inputs`, etc.), so Program 1 checks
  `action.type == "collect_inputs"` before treating it as a signature —
  anything else is acknowledged and ignored.
- **Failures use a separate event**, `terminal.reader.action_failed` (customer
  canceled, or the reader sat untouched for 2 minutes and timed out). Program
  1 logs the failure code/message and acknowledges it — there's no signature
  to forward.
- **Stripe only retains these files for 7 days.** Program 1 downloads
  immediately inside the webhook handler, so this isn't a problem for the
  live flow, but it does mean the download call is synchronous and its
  failure (Stripe API error, network blip) is treated as retryable (503→
  Stripe retries the webhook) rather than silently dropped.

One thing still **unconfirmed**: where the account number actually lives in
your event payload — the sample you shared doesn't include a `metadata`
field, so the current default (`ACCOUNT_NUMBER_PATH=metadata.account_number`)
is a placeholder. If you pass `account_number` as metadata when creating the
`collect_inputs` action, check where Stripe echoes it back in a real event
and point `ACCOUNT_NUMBER_PATH` at that. If it comes from somewhere else
entirely (looked up from the linked PaymentIntent, the connected account ID,
etc.), tell me and I'll adjust `extract_account_number()` to match.

## Signature/stamp placement (Program 2)

Configurable via env vars in `program2_contract_merge/config.py` — all
coordinates are PDF points (72/inch), origin bottom-left of the page, page
number is 1-indexed (`-1` = last page):

| Var | Default | Meaning |
|---|---|---|
| `SIGNATURE_PAGE_NUMBER` | `-1` | Page the signature is drawn on |
| `SIGNATURE_X` / `SIGNATURE_Y` | `72` / `110` | Anchor point (bottom-left of the signature's bounding box) |
| `SIGNATURE_MAX_WIDTH` / `SIGNATURE_MAX_HEIGHT` | `220` / `70` | Box the signature is scaled to fit inside, aspect ratio preserved |
| `STAMP_PAGE_NUMBER`, `STAMP_X`, `STAMP_Y` | `-1`, `72`, `70` | Where the account-number/saved-at line is drawn |
| `STAMP_TEXT_TEMPLATE` | `"Account: {account_number}    Signed: {saved_at}"` | Format string |
| `STAMP_DATETIME_FORMAT` | `"%Y-%m-%d %H:%M:%S UTC"` | strftime pattern for the saved-at timestamp |

These defaults were only tuned against the test fixture contract generated
for local testing — **you'll need to adjust `SIGNATURE_X/Y` and
`STAMP_X/Y` against your real contract template** so the signature lands on
the actual signature line rather than wherever these placeholders happen to
put it.

The "saved at" timestamp is when Program 2 processes the request (not when
Stripe captured the signature — that's `captured_at`, still logged
separately), matching "the time and date it was saved."

## Where signed contracts are saved (Program 2)

| Var | Default | Meaning |
|---|---|---|
| `OUTPUT_DIR` | `/var/contract-pipeline/signed` | Directory the finished PDFs land in - set this to a real, backed-up path |
| `FILENAME_TEMPLATE` | `{account_number}_{saved_at}.pdf` | Filename format - substitutes account number and save timestamp |
| `FILENAME_DATETIME_FORMAT` | `%Y%m%d-%H%M%S` | strftime pattern for `{saved_at}` in the *filename* - deliberately separate from `STAMP_DATETIME_FORMAT` (the on-page one), since filenames can't safely contain colons/spaces |

Example: `ACC-00123_20260806-164014.pdf`.

A few things `storage.py` handles beyond the happy path, since the account
number ultimately traces back to a webhook payload relayed over the network:

- **Path traversal**: the account number is sanitized to `[A-Za-z0-9_-]`
  before it touches a filename, and the resolved path is double-checked to
  still be inside `OUTPUT_DIR`. Tested with `../../etc/passwd` and slash-laden
  input - both get contained, not followed.
- **Collisions**: if two signatures for the same account land inside the
  same timestamp resolution window (e.g. `FILENAME_DATETIME_FORMAT` only
  has second resolution and two events land in the same second), a numeric
  suffix (`_1`, `_2`, ...) is appended rather than silently overwriting an
  existing signed contract. Verified by firing two events back-to-back.
- **Atomic writes**: the PDF is spooled to a temp file in the same directory
  and `os.replace()`d into place, so a crash mid-write can't leave a
  truncated/corrupt file sitting at the real filename.

## Running the smoke test locally

This exercises the full chain — including the real file-ID → Files API
download step — without real Stripe Terminal hardware or a live Stripe
account, using a fake Stripe Files server and a correctly-signed fake event.

```bash
# terminal 1 - fake Stripe Files API (serves the file ID -> SVG download)
python3 scripts/fake_stripe_files_server.py   # listens on :9999

# terminal 2 - Program 2
cd program2_contract_merge
RELAY_SHARED_SECRET=test-shared-secret \
RECEIVED_DUMP_DIR=/tmp/program2_received \
OUTPUT_DIR=/tmp/program2_signed \
PORT=8443 python3 app.py

# terminal 3 - Program 1
cd program1_stripe_relay
STRIPE_WEBHOOK_SECRET=whsec_test_secret \
STRIPE_API_KEY=sk_test_fake \
STRIPE_API_BASE=http://localhost:9999 \
CONTRACT_TEMPLATE_PATH=/path/to/some/blank_contract.pdf \
PROGRAM2_URL=http://localhost:8443/webhook/contract \
RELAY_SHARED_SECRET=test-shared-secret \
PORT=5000 python3 app.py

# terminal 4 - fire a fake signed Stripe event at Program 1
STRIPE_WEBHOOK_SECRET=whsec_test_secret \
TEST_ACCOUNT_NUMBER=ACC-00123 \
python3 scripts/simulate_stripe_event.py

# also try the failure path (should be acknowledged, nothing forwarded)
STRIPE_WEBHOOK_SECRET=whsec_test_secret \
python3 scripts/simulate_stripe_failure_event.py
```

The real, finished contract lands in `/tmp/program2_signed/` as
`ACC-00123_<timestamp>.pdf`. `/tmp/program2_received/ACC-00123/` still gets
the raw debug inputs (`blank_contract.pdf`, `signature.svg`, `meta.txt` -
the latter now also records the final saved path) for troubleshooting a bad
merge without re-triggering a signature.

Confirmed working end-to-end in this environment: Program 1 actually
calling out to `GET /v1/files/<id>` then `GET /v1/files/<id>/contents` for
the download (visible in Program 1's logs); the merge producing a correctly
stamped single-page PDF with `/AccountNumber` and `/SignedAt` metadata set;
the failure event being acknowledged without any forward attempt; and two
back-to-back events for the same account both landing safely on disk with
distinct filenames rather than one clobbering the other. **In production,
omit `STRIPE_API_BASE`** so the SDK talks to the real `api.stripe.com`.

## Security notes

- Program 1 → Program 2 traffic should run over TLS in production
  (`PROGRAM2_URL` uses `https://`); the Flask dev server here has no TLS —
  put nginx/caddy or `ssl_context=` in front of it before deploying.
- The HMAC signature includes a timestamp and is rejected outside a 5-minute
  tolerance window, so a captured request can't be replayed later to
  re-print or re-store an old contract.
- `RELAY_SHARED_SECRET` and `STRIPE_WEBHOOK_SECRET` must never be committed;
  `.env` files are for local dev only — use a secrets manager or systemd
  environment file in production.

"""
Saves the finished, signed contract PDF to disk under a filename that
encodes the account number and the save timestamp.

Two things this deliberately guards against, since the account number
ultimately originates from a Stripe webhook payload relayed over the
network:
  - Path traversal / injection: the account number is sanitized down to a
    safe character set before it's used in a filename, and the resolved
    output path is checked to still be inside OUTPUT_DIR.
  - Partial writes: the PDF is spooled to a temp file and atomically
    renamed into place, so a crash mid-write can never leave a corrupt file
    sitting at the real filename.
"""
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path


class StorageError(Exception):
    """Raised when the signed contract can't be safely saved."""


def sanitize_for_filename(value: str, max_length: int = 100) -> str:
    """Reduce a string to a safe filename component: letters, digits, dash,
    underscore only. Strips anything else (including path separators and
    '..'), so it can't be used to escape the output directory."""
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", value)
    cleaned = cleaned.strip("._- ")  # avoid leading dots (hidden files) / stray separators
    if not cleaned:
        raise StorageError(f"Account number {value!r} sanitizes to an empty filename component")
    return cleaned[:max_length]


def build_output_path(
    output_dir: Path,
    account_number: str,
    saved_at: datetime,
    filename_template: str,
    filename_datetime_format: str,
) -> Path:
    safe_account = sanitize_for_filename(account_number)
    saved_at_str = saved_at.strftime(filename_datetime_format)
    filename = filename_template.format(account_number=safe_account, saved_at=saved_at_str)
    filename = filename.replace("/", "_").replace("\\", "_")  # in case a hand-edited template adds one
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"

    output_dir_resolved = output_dir.resolve()
    candidate = (output_dir_resolved / filename).resolve()
    if candidate != output_dir_resolved and output_dir_resolved not in candidate.parents:
        # Shouldn't be reachable given sanitize_for_filename() above - this
        # is defense in depth in case the template or format string changes.
        raise StorageError(f"Resolved output path {candidate} escapes OUTPUT_DIR {output_dir_resolved}")

    # Don't clobber an existing signed contract if two events for the same
    # account land inside the same time-resolution window - append a suffix.
    if candidate.exists():
        stem, suffix = candidate.stem, candidate.suffix
        for n in range(1, 1000):
            alt = candidate.with_name(f"{stem}_{n}{suffix}")
            if not alt.exists():
                candidate = alt
                break
        else:
            raise StorageError(f"Could not find a free filename near {candidate}")

    return candidate


def save_contract(pdf_bytes: bytes, path: Path) -> None:
    """Atomic write: spool to a temp file in the same directory, then
    os.replace() into place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(pdf_bytes)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise

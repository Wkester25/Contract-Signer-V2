"""
Sends the finished, signed contract PDF to a physical printer via CUPS.

Shells out to the standard `lp` command (from cups-client) rather than
binding to libcups directly - `lp` is present wherever CUPS is set up,
needs no compiled Python extension, and is exactly what you'd run by hand
to confirm printing works.
"""
import logging
import subprocess
from pathlib import Path

log = logging.getLogger("program2.printing")


class PrintError(Exception):
    """Raised when the contract can't be handed off to the printer."""


def _parse_options(options: str) -> list:
    """Turns "media=Letter,sides=one-sided" into
    ["-o", "media=Letter", "-o", "sides=one-sided"]."""
    flags = []
    for pair in options.split(","):
        pair = pair.strip()
        if pair:
            flags += ["-o", pair]
    return flags


def print_contract(
    path: Path,
    printer_name: str,
    copies: int,
    options: str,
    timeout_seconds: float,
) -> str:
    """Submits `path` to CUPS via `lp`. Returns whatever `lp` printed (e.g.
    "request id is testprinter-3 (1 file(s))"). Raises PrintError if `lp`
    isn't installed, the job is rejected, or CUPS doesn't respond in time."""
    if not path.is_file():
        raise PrintError(f"Cannot print - file does not exist: {path}")

    cmd = ["lp"]
    if printer_name:
        cmd += ["-d", printer_name]
    if copies and copies != 1:
        cmd += ["-n", str(copies)]
    cmd += _parse_options(options)
    cmd += [str(path)]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds)
    except FileNotFoundError as exc:
        raise PrintError(
            "`lp` command not found - install cups-client (or your distro's CUPS client tools)"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise PrintError(f"`lp` timed out after {timeout_seconds}s running: {' '.join(cmd)}") from exc

    if result.returncode != 0:
        raise PrintError(
            f"`lp` exited {result.returncode}: {result.stderr.strip() or result.stdout.strip()}"
        )

    job_info = result.stdout.strip()
    log.info("Submitted print job for %s: %s", path, job_info)
    return job_info

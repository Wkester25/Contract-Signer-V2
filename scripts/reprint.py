"""
Manually (re)print an already-saved signed contract - e.g. after Program 2
logged a print failure ("saved+recorded, NOT printed") and you want to
retry just the printing step, without re-running the whole webhook flow
(which would create a duplicate saved file and DB row).

Usage:
    python3 scripts/reprint.py /var/contract-pipeline/signed/ACC-00123_20260806-164014.pdf
    python3 scripts/reprint.py --printer "Front-Desk-Printer" --copies 2 path/to/file.pdf

Defaults to the same PRINTER_NAME/PRINT_COPIES/PRINT_OPTIONS/
PRINT_TIMEOUT_SECONDS env vars Program 2 uses, so it prints to the same
destination unless overridden.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "program2_contract_merge"))
from printing import print_contract, PrintError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdf_path", type=Path)
    parser.add_argument("--printer", default=os.environ.get("PRINTER_NAME", ""))
    parser.add_argument("--copies", type=int, default=int(os.environ.get("PRINT_COPIES", "1")))
    parser.add_argument("--options", default=os.environ.get("PRINT_OPTIONS", ""))
    parser.add_argument(
        "--timeout", type=float, default=float(os.environ.get("PRINT_TIMEOUT_SECONDS", "30"))
    )
    args = parser.parse_args()

    try:
        job_info = print_contract(args.pdf_path, args.printer, args.copies, args.options, args.timeout)
    except PrintError as exc:
        print(f"Print failed: {exc}", file=sys.stderr)
        return 1

    print(f"Submitted: {job_info}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

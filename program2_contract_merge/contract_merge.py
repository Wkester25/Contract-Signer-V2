"""
Merges an SVG signature and an account-number/timestamp stamp onto a blank
PDF contract.

Pipeline:
  1. Parse the signature SVG into a reportlab Drawing (svglib).
  2. Scale it to fit inside a configured box, preserving aspect ratio.
  3. Render the signature + stamp text onto a same-size transparent overlay
     PDF page (reportlab canvas).
  4. Merge that overlay onto the target page of the contract (pypdf).
  5. Write account number / signed-at into the PDF's document metadata too,
     so it's machine-readable and not just printed text.
"""
import io
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.graphics import renderPDF
from reportlab.pdfgen import canvas
from svglib.svglib import svg2rlg


class ContractMergeError(Exception):
    """Raised when the signature or contract can't be merged."""


@dataclass
class Placement:
    """Where to draw something on a page, in PDF points from the bottom-left."""

    page_number: int  # 1-indexed; -1 means last page
    x: float
    y: float


def _resolve_page_index(page_number: int, page_count: int) -> int:
    """Convert a 1-indexed page number (or -1 for "last") into a 0-indexed one."""
    if page_number == -1:
        return page_count - 1
    index = page_number - 1
    if not (0 <= index < page_count):
        raise ContractMergeError(
            f"Configured page number {page_number} is out of range for a "
            f"{page_count}-page contract"
        )
    return index


def _svg_bytes_to_drawing(svg_bytes: bytes):
    """svglib's svg2rlg wants a path (or something it can hand to an XML
    parser that supports seeking), so the bytes are spooled through a temp
    file rather than passed in-memory."""
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as tmp:
        tmp.write(svg_bytes)
        tmp_path = tmp.name
    try:
        drawing = svg2rlg(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if drawing is None:
        raise ContractMergeError("svglib could not parse the signature SVG")
    return drawing


def _fit_drawing(drawing, max_width: float, max_height: float):
    """Scale a reportlab Drawing to fit inside (max_width, max_height),
    preserving aspect ratio. Standard svglib resizing idiom."""
    if drawing.width <= 0 or drawing.height <= 0:
        raise ContractMergeError("Signature SVG has zero width or height")

    scale = min(max_width / drawing.width, max_height / drawing.height)
    drawing.width *= scale
    drawing.height *= scale
    drawing.scale(scale, scale)
    return drawing


def _build_overlay_pdf(
    page_width: float,
    page_height: float,
    drawing,  # None if this page doesn't get the signature
    signature_xy: tuple[float, float],
    stamp_text: str,  # "" if this page doesn't get the stamp
    stamp_xy: tuple[float, float],
    stamp_font_name: str,
    stamp_font_size: float,
) -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(page_width, page_height))

    if drawing is not None:
        renderPDF.draw(drawing, c, signature_xy[0], signature_xy[1])

    if stamp_text:
        c.setFont(stamp_font_name, stamp_font_size)
        c.drawString(stamp_xy[0], stamp_xy[1], stamp_text)

    c.showPage()
    c.save()
    return buffer.getvalue()


def merge_signature_and_stamp(
    contract_bytes: bytes,
    signature_svg_bytes: bytes,
    account_number: str,
    saved_at_text: str,
    signature_placement: Placement,
    signature_max_width: float,
    signature_max_height: float,
    stamp_placement: Placement,
    stamp_text_template: str,
    stamp_font_name: str,
    stamp_font_size: float,
) -> bytes:
    """Returns the finished PDF (contract + signature + stamp) as bytes."""
    try:
        reader = PdfReader(io.BytesIO(contract_bytes))
    except Exception as exc:  # pypdf raises various error types for bad PDFs
        raise ContractMergeError(f"Contract template is not a readable PDF: {exc}") from exc

    if len(reader.pages) == 0:
        raise ContractMergeError("Contract template PDF has no pages")

    sig_page_index = _resolve_page_index(signature_placement.page_number, len(reader.pages))
    stamp_page_index = _resolve_page_index(stamp_placement.page_number, len(reader.pages))

    drawing = _svg_bytes_to_drawing(signature_svg_bytes)
    drawing = _fit_drawing(drawing, signature_max_width, signature_max_height)

    stamp_text = stamp_text_template.format(account_number=account_number, saved_at=saved_at_text)

    writer = PdfWriter()
    for index, page in enumerate(reader.pages):
        if index in (sig_page_index, stamp_page_index):
            page_width = float(page.mediabox.width)
            page_height = float(page.mediabox.height)
            overlay_bytes = _build_overlay_pdf(
                page_width,
                page_height,
                drawing if index == sig_page_index else None,
                (signature_placement.x, signature_placement.y),
                stamp_text if index == stamp_page_index else "",
                (stamp_placement.x, stamp_placement.y),
                stamp_font_name,
                stamp_font_size,
            )
            overlay_reader = PdfReader(io.BytesIO(overlay_bytes))
            page.merge_page(overlay_reader.pages[0])
        writer.add_page(page)

    writer.add_metadata(
        {
            "/AccountNumber": account_number,
            "/SignedAt": saved_at_text,
            "/Producer": "contract-signing-pipeline",
        }
    )

    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()

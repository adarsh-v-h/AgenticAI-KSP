"""Tests for report text extraction (routers.reports.extract_report_text).

Covers the lean, stdlib-only format set we support, and verifies that formats
needing a heavy/fragile parser (PDF) or unknown binary types are rejected with
a clear, officer-facing message instead of producing garbage.
"""

import io
import zipfile

import pytest

from routers.reports import (
    UnsupportedReportFormat,
    extract_report_text,
)


def _make_docx(paragraphs: list[str]) -> bytes:
    """Build a minimal valid .docx (zip with word/document.xml)."""
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(
        f'<w:p><w:r><w:t>{p}</w:t></w:r></w:p>' for p in paragraphs
    )
    document_xml = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{ns}"><w:body>{body}</w:body></w:document>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", document_xml)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# DOCX
# --------------------------------------------------------------------------- #


def test_docx_extraction_returns_paragraph_text():
    raw = _make_docx(["First paragraph.", "Second paragraph about theft."])
    text = extract_report_text(raw, "report.docx", "")
    assert "First paragraph." in text
    assert "Second paragraph about theft." in text


def test_docx_detected_by_mime_type():
    raw = _make_docx(["Detected by mime."])
    text = extract_report_text(
        raw,
        "noextension",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert "Detected by mime." in text


# --------------------------------------------------------------------------- #
# Plain text / Markdown / HTML
# --------------------------------------------------------------------------- #


def test_plain_text_extraction():
    raw = "Incident report: repeated thefts in Koramangala.".encode()
    text = extract_report_text(raw, "notes.txt", "text/plain")
    assert "repeated thefts in Koramangala" in text


def test_markdown_extraction():
    raw = "# Heading\n\n- bullet one\n- bullet two".encode()
    text = extract_report_text(raw, "summary.md", "text/markdown")
    assert "bullet one" in text


def test_html_tags_are_stripped():
    raw = (
        "<html><head><style>.x{color:red}</style></head>"
        "<body><h1>Title</h1><p>Body &amp; text</p>"
        "<script>alert(1)</script></body></html>"
    ).encode()
    text = extract_report_text(raw, "page.html", "text/html")
    assert "Title" in text
    assert "Body & text" in text  # entities unescaped
    assert "<h1>" not in text     # tags stripped
    assert "alert(1)" not in text  # script content removed


# --------------------------------------------------------------------------- #
# Rejected formats
# --------------------------------------------------------------------------- #


def test_pdf_is_rejected_with_helpful_message():
    raw = b"%PDF-1.7\n...binary..."
    with pytest.raises(UnsupportedReportFormat) as exc:
        extract_report_text(raw, "report.pdf", "application/pdf")
    assert "PDF" in exc.value.message


def test_unknown_binary_type_is_rejected():
    raw = b"\x00\x01\x02\x03binarygibberish"
    with pytest.raises(UnsupportedReportFormat):
        extract_report_text(raw, "evidence.bin", "application/octet-stream")

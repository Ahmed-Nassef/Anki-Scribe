import zipfile

import pymupdf
import pytest

from app import formats
from app.store import Store


def test_math_alphanumerics_become_letters():
    assert formats.normalise_math("𝐴𝐵 + 𝝁 = 2𝜎") == "AB + μ = 2σ"


def test_superscripts_and_subscripts_fold():
    assert formats.normalise_math("CO₂ + H₂O") == "CO_{2} + H_{2}O"
    assert formats.normalise_math("4 m²") == "4 m^{2}"
    assert formats.normalise_math("10⁻⁶") == "10^{-6}"


def test_fraction_glyphs_become_a_ratio():
    assert formats.normalise_math("½ dose") == "1/2 dose"


def test_latex_symbols_for_a_formula_line():
    assert (
        formats.normalise_math("σ² = 4 × 10⁻⁶", latex_symbols=True)
        == "\\sigma^{2} = 4 \\times 10^{-6}"
    )


def test_prose_is_not_mistaken_for_a_formula():
    assert not formats.looks_like_math("The variance is small in this model.")
    assert not formats.looks_like_math("Make-A-Wish’s campaign")
    assert not formats.looks_like_math("$395. Today, that")
    assert not formats.looks_like_math("β-blockers reduce heart rate")


def test_formula_lines_are_recognised():
    assert formats.looks_like_math("CO = HR × SV")
    assert formats.looks_like_math("S = μᵀw − μ₀")
    assert formats.looks_like_math("fvt= fvt−1 + Dt")


def test_mark_math_wraps_once_and_leaves_prices_alone():
    assert formats.mark_math("CO = HR × SV", True) == "$CO = HR × SV$"
    assert formats.mark_math("CO = HR × SV", False) == "CO = HR × SV"
    assert formats.mark_math("costs $5", True) == "costs $5"


def make_pdf(path, lines):
    pdf = pymupdf.open()
    page = pdf.new_page(width=600, height=800)
    for index, (text, size) in enumerate(lines):
        page.insert_text((60, 80 + index * 44), text, fontsize=size)
    pdf.save(path)
    pdf.close()
    return path


def test_a_formula_line_is_marked_in_the_extracted_text(tmp_path):
    source = make_pdf(
        tmp_path / "formulas.pdf",
        [
            ("CO = HR × SV", 12),
            ("Cardiac output is the product of heart rate.", 11),
        ],
    )
    store = Store(tmp_path / "documents")
    doc = store.create_pdf_path(source, "formulas.pdf")

    line = next(item for item in doc.pages[0].lines if "CO = HR" in item["text"])
    assert line.get("math") is True
    prose = next(item for item in doc.pages[0].lines if "Cardiac output" in item["text"])
    assert prose.get("math") is None

    text = store.extract_chunks(doc)["chunks"][0]["text"]
    assert "$CO = HR \\times SV$" in text
    assert "Cardiac output is the product of heart rate." in text
    assert "$Cardiac" not in text


def test_an_epub_table_arrives_as_pipe_rows(tmp_path):
    chapter = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Chapter</title></head>
<body><h1>Chapter 1</h1>
<table>
  <tr><th>Drug</th><th>Dose</th></tr>
  <tr><td>Metoprolol</td><td>50 mg</td></tr>
  <tr><td>Ramipril</td><td>5 mg</td></tr>
</table>
<p>Both lower blood pressure.</p></body></html>"""
    opf = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:uuid:test</dc:identifier><dc:title>Tables</dc:title>
  </metadata>
  <manifest><item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/></manifest>
  <spine><itemref idref="c1"/></spine>
</package>"""
    container = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf"
    media-type="application/oebps-package+xml"/></rootfiles>
</container>"""
    source = tmp_path / "tables.epub"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/content.opf", opf)
        archive.writestr("OEBPS/ch1.xhtml", chapter)

    store = Store(tmp_path / "documents")
    doc = store.create_epub_path(source, "tables.epub")
    text = store.extract_chunks(doc)["chunks"][0]["text"]
    assert "| Drug | Dose |" in text
    assert "| --- | --- |" in text
    assert "| Metoprolol | 50 mg |" in text
    assert "Both lower blood pressure." in text

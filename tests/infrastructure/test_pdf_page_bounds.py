from __future__ import annotations

import ctypes
from contextlib import closing
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from PIL import ImageChops, ImageStat

from lib.infrastructure.document_conversion.docling_stack import converter
from lib.infrastructure.document_conversion.docling_stack.pdf import bounded_pdf


def make_pdf(path, *, oversized=True, rotation=0, offset=0):
    with pdfium.PdfDocument.new() as document:
        width, height = (7680, 4320) if oversized else (720, 405)
        with closing(document.new_page(width, height)) as page:
            text = pdfium.raw.FPDFPageObj_NewTextObj(document, b"Helvetica", 150)
            value = (ctypes.c_ushort * 7)(*map(ord, "Everon"), 0)
            assert pdfium.raw.FPDFText_SetText(text, value)
            pdfium.raw.FPDFPageObj_Transform(text, 1, 0, 0, 1, 500, 500)
            page.insert_obj(pdfium.PdfObject(text))
            page.gen_content()
            page.set_rotation(rotation)
            if offset:
                page.set_cropbox(offset, offset, 7000, 4000)
        with closing(document.new_page(612, 792)):
            pass
        document.save(path)


@pytest.mark.parametrize("rotation,offset", [(0, 0), (90, 0), (0, 100), (270, 100)])
def test_bounded_pdf_preserves_content_geometry_and_original(
    tmp_path, rotation, offset
):
    source = tmp_path / "large.pdf"
    make_pdf(source, rotation=rotation, offset=offset)
    original = source.read_bytes()
    with pdfium.PdfDocument(source) as document, closing(document[0]) as page:
        original_size = page.get_size()
        with closing(page.render(scale=720 / max(original_size))) as bitmap:
            before = bitmap.to_pil().copy()

    with bounded_pdf(str(source)) as prepared:
        assert prepared != str(source)
        with pdfium.PdfDocument(prepared) as document:
            assert len(document) == 2
            with closing(document[0]) as page:
                assert max(page.get_size()) == pytest.approx(1440)
                assert page.get_width() / page.get_height() == pytest.approx(
                    original_size[0] / original_size[1]
                )
                assert page.get_rotation() == rotation
                with closing(page.get_textpage()) as text:
                    assert "Everon" in text.get_text_range()
                with closing(page.render(scale=0.5)) as bitmap:
                    after = bitmap.to_pil().copy()
                assert before.size == after.size
                difference = ImageStat.Stat(ImageChops.difference(before, after))
                assert max(difference.mean) < 1
            with closing(document[1]) as page:
                assert page.get_size() == (612, 792)
    assert not Path(prepared).exists()
    assert source.read_bytes() == original


def test_normal_pdf_is_passed_through_without_rewriting(tmp_path):
    source = tmp_path / "normal.pdf"
    make_pdf(source, oversized=False)
    original = source.read_bytes()
    with bounded_pdf(str(source)) as prepared:
        assert prepared == str(source)
    assert source.read_bytes() == original


@pytest.mark.parametrize("force_ocr", [False, True])
def test_docling_receives_bounded_pdf_and_cleans_up_on_error(
    tmp_path, monkeypatch, force_ocr
):
    source = tmp_path / "large.pdf"
    make_pdf(source)
    paths = []

    def convert(path):
        paths.append(Path(path))
        with pdfium.PdfDocument(path) as document, closing(document[0]) as page:
            assert max(page.get_size()) <= 1440
        raise RuntimeError("conversion failed")

    monkeypatch.setattr(
        converter,
        "convert_document_force_ocr" if force_ocr else "convert_with_docling",
        convert,
    )
    with pytest.raises(RuntimeError, match="conversion failed"):
        converter._execute_docling(filepath=str(source), force_ocr=force_ocr)
    assert paths and paths[0] != source and not paths[0].exists()
    assert source.exists()

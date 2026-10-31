from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from lib.infrastructure.document_conversion.docling_stack.outlined_text import (
    VectorShape,
    has_outlined_text,
    outlined_text_pages,
)
from lib.infrastructure.document_conversion.docling_stack.selective_ocr import SelectiveOcrModel

PAGE = (0, 0, 800, 600)
ROWS = [VectorShape((100, 300, 400, 320), 180), VectorShape((100, 260, 350, 280), 140)]


def test_compound_outlines_require_multiple_uncovered_text_rows():
    assert has_outlined_text(ROWS, [], PAGE)
    assert not has_outlined_text(ROWS[:1], [], PAGE)  # isolated outlined logo
    assert not has_outlined_text(ROWS, [s.bounds for s in ROWS], PAGE)


def test_ordinary_graphics_and_marginal_footers_do_not_trigger():
    shapes = [
        VectorShape(PAGE, 5),  # background
        VectorShape((100, 300, 400, 302), 100),  # thin chart line
        VectorShape((100, 200, 400, 350), 500),  # large illustration
        VectorShape((100, 300, 400, 320), 5),  # simple rectangle
        VectorShape((100, 10, 400, 20), 500),
        VectorShape((100, 25, 400, 35), 500),
    ]
    assert not has_outlined_text(shapes, [], PAGE)


def test_individual_glyphs_need_aligned_nearby_rows():
    glyphs = [VectorShape((100 + x * 12, y, 108 + x * 12, y + 15), 16)
              for y in [200, 240] for x in range(8)]
    assert has_outlined_text(glyphs, [], PAGE)
    spaced = [VectorShape((100 + x * 70, y, 108 + x * 70, y + 15), 16)
              for y in [200, 240] for x in range(8)]
    assert not has_outlined_text(spaced, [], PAGE)


def test_detector_is_scale_and_crop_origin_independent():
    for scale, offset in [(0.5, 0), (4, 100)]:
        transform = lambda b: tuple(v * scale + offset for v in b)
        assert has_outlined_text(
            [VectorShape(transform(s.bounds), s.segments) for s in ROWS],
            [], transform(PAGE),
        )


def test_detector_reads_vector_pdf_and_preserves_source(tmp_path):
    import pypdfium2 as pdfium
    from contextlib import closing

    source = tmp_path / 'mixed.pdf'
    with pdfium.PdfDocument.new() as document:
        with closing(document.new_page(800, 600)) as page:
            for y in [260, 300]:
                # Each row is a compound path of repeated outlined E glyphs.
                path = pdfium.raw.FPDFPageObj_CreateNewPath(100, y)
                for x in range(100, 400, 20):
                    pdfium.raw.FPDFPath_MoveTo(path, x, y)
                    for dx, dy in [(0,20),(12,20),(12,17),(3,17),(3,12),(10,12),
                                   (10,9),(3,9),(3,3),(12,3),(12,0),(0,0)]:
                        pdfium.raw.FPDFPath_LineTo(path, x+dx, y+dy)
                    pdfium.raw.FPDFPath_Close(path)
                pdfium.raw.FPDFPath_SetDrawMode(path, 1, False)
                page.insert_obj(pdfium.PdfObject(path))
            page.gen_content()
        with closing(document.new_page(800, 600)):
            pass
        document.save(source)
    original = source.read_bytes()
    assert outlined_text_pages(source, [1, 2]) == {1}
    assert outlined_text_pages(source, [2]) == set()
    assert source.read_bytes() == original


class Parsed:
    def __init__(self, text):
        self.textline_cells = [SimpleNamespace(text=text)]
        self.word_cells = ['original words']

    def model_copy(self, *, deep):
        return deepcopy(self)


class Page:
    def __init__(self, number):
        self.page_no = number
        self._backend = SimpleNamespace(is_valid=lambda: True)
        self.parsed_page = Parsed('Original native text that must survive OCR failure.')

    @property
    def cells(self):
        return self.parsed_page.textline_cells


@pytest.mark.parametrize('outcome', ['good', 'empty', 'reduced', 'error'])
def test_selective_ocr_preserves_order_and_restores_original_on_failure(monkeypatch, outcome):
    import lib.infrastructure.document_conversion.docling_stack.selective_ocr as module
    monkeypatch.setattr(module, 'outlined_text_pages', lambda _path, _pages: {8})
    calls = []

    def standard(_conv, pages):
        for page in pages:
            calls.append(('standard', page.page_no))
            assert page.parsed_page.word_cells == ['original words']
            yield page

    def full(_conv, pages):
        for page in pages:
            calls.append(('full', page.page_no))
            page.parsed_page.word_cells = []
            page.parsed_page.textline_cells = [SimpleNamespace(text={
                'good': 'Original native text that must survive OCR failure. Founder and CEO.',
                'empty': '', 'reduced': 'Hi', 'error': '',
            }[outcome])]
            if outcome == 'error':
                raise RuntimeError('OCR unavailable')
            yield page

    def merge(cells, page):
        page.parsed_page.textline_cells = cells

    standard.post_process_cells = merge
    pages = [Page(7), Page(8), Page(9)]
    result = list(SelectiveOcrModel(standard, lambda: full)(
        SimpleNamespace(input=SimpleNamespace(file=Path('example.pdf'))), pages,
    ))
    assert result == pages
    assert calls[:2] == [('standard', 7), ('full', 8)]
    assert calls[-1] == ('standard', 9)
    if outcome == 'good':
        assert ('standard', 8) not in calls
        assert 'CEO' in pages[1].cells[0].text
    else:
        assert ('standard', 8) in calls
        assert pages[1].parsed_page.word_cells == ['original words']
        assert pages[1].cells[0].text.startswith('Original native text')


def test_inspection_failure_falls_back_to_normal_ocr(monkeypatch, caplog):
    import lib.infrastructure.document_conversion.docling_stack.selective_ocr as module

    def fail(*args):
        raise RuntimeError('Cannot inspect PDF')

    monkeypatch.setattr(module, 'outlined_text_pages', fail)
    pages = [Page(1)]
    model = SelectiveOcrModel(lambda _conv, batch: iter(batch),
                              lambda *_args: pytest.fail('Full OCR must not run'))
    assert list(model(SimpleNamespace(input=SimpleNamespace(file=Path('file.pdf'))), pages)) == pages
    assert 'using normal OCR' in caplog.text


def test_normal_pages_do_not_initialize_full_page_ocr(monkeypatch):
    import lib.infrastructure.document_conversion.docling_stack.selective_ocr as module
    monkeypatch.setattr(module, 'outlined_text_pages', lambda *_args: set())
    pages = [Page(1), Page(2)]
    model = SelectiveOcrModel(lambda _conv, batch: iter(batch),
                              lambda: pytest.fail('Do not initialize unused OCR engine'))
    assert list(model(SimpleNamespace(input=SimpleNamespace(file=Path('plain.pdf'))), pages)) == pages


def test_shared_model_keeps_page_selection_document_local(monkeypatch):
    import lib.infrastructure.document_conversion.docling_stack.selective_ocr as module
    monkeypatch.setattr(module, 'outlined_text_pages',
                        lambda path, _pages: {1} if path.name == 'outline.pdf' else set())
    calls = []
    initialized = []

    def full_factory():
        initialized.append(True)
        def full(conv, pages):
            calls.append(conv.input.file.name)
            yield from pages
        return full

    def standard(_conv, batch):
        yield from batch
    standard.post_process_cells = lambda cells, page: None
    model = SelectiveOcrModel(standard, full_factory)
    for filename in ['outline.pdf', 'plain.pdf', 'outline.pdf']:
        list(model(SimpleNamespace(input=SimpleNamespace(file=Path(filename))), [Page(1)]))
    assert calls == ['outline.pdf', 'outline.pdf']
    assert initialized == [True]


def test_full_page_ocr_adds_outlines_without_replacing_native_text(monkeypatch):
    import lib.infrastructure.document_conversion.docling_stack.selective_ocr as module
    from docling.models.stages.ocr.ocr_mac_model import OcrMacModel
    from docling.datamodel.pipeline_options import OcrMacOptions
    from docling.datamodel.accelerator_options import AcceleratorOptions
    from docling_core.types.doc import BoundingBox
    from docling_core.types.doc.page import BoundingRectangle, TextCell

    def cell(text, top, ocr=False):
        return TextCell(index=0, text=text, orig=text, from_ocr=ocr,
                        rect=BoundingRectangle.from_bounding_box(
                            BoundingBox(l=10, t=top, r=300, b=top+20)))

    monkeypatch.setattr(module, 'outlined_text_pages', lambda *_args: {1})
    standard = OcrMacModel(enabled=False, artifacts_path=None,
                           options=OcrMacOptions(), accelerator_options=AcceleratorOptions())
    page = Page(1)
    page.parsed_page.textline_cells = [cell('https://example.test/pilot0', 10)]

    def full(_conv, pages):
        for page in pages:
            page.parsed_page.word_cells = []
            page.parsed_page.textline_cells = [
                cell('https://example.test/pilotO', 10, True),
                cell('Founder & CEO', 50, True),
            ]
            yield page

    result = list(SelectiveOcrModel(standard, lambda: full)(
        SimpleNamespace(input=SimpleNamespace(file=Path('mixed.pdf'))), [page],
    ))
    assert result == [page]
    assert [c.text for c in page.cells] == ['https://example.test/pilot0', 'Founder & CEO']
    assert page.parsed_page.word_cells == ['original words']


@pytest.mark.parametrize('force', [False, True])
def test_shared_docling_entry_keeps_source_as_path(monkeypatch, tmp_path, force):
    from lib.infrastructure.document_conversion.docling_stack import docling
    source = tmp_path / 'input.pdf'
    calls = []

    def convert(path):
        calls.append(path)
        return SimpleNamespace(document='document')

    monkeypatch.setattr(docling, 'get_force_ocr_converter' if force else 'get_converter',
                        lambda: SimpleNamespace(convert=convert))
    monkeypatch.setattr(docling, 'export_document_markdown', lambda _doc: 'markdown')
    operation = docling.convert_document_force_ocr if force else docling.convert_document
    assert operation(str(source)) == 'markdown'
    assert calls == [source]
    assert isinstance(calls[0], Path)

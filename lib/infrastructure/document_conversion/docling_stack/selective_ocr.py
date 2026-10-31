"""Page-selective OCR inside Docling, before layout and reading-order analysis."""
from __future__ import annotations

import threading

from docling.models.factories import get_ocr_factory
from docling.pipeline.standard_pdf_pipeline import StandardPdfPipeline

from lib.infrastructure.document_conversion.docling_stack.outlined_text import (
    outlined_text_pages,
)
from lib.infrastructure.logging import get_logger

logger = get_logger(__name__)


def _text_size(cells) -> int:
    return sum(sum(c.isalnum() for c in cell.text) for cell in cells)


class SelectiveOcrModel:
    def __init__(self, standard, full_page_factory):
        self.standard = standard
        self._full_page_factory = full_page_factory
        self._full_page = None
        self._init_lock = threading.Lock()

    def _full_page_model(self):
        with self._init_lock:
            if self._full_page is None:
                self._full_page = self._full_page_factory()
        return self._full_page

    def __call__(self, conv_res, page_batch):
        pages = list(page_batch)
        eligible = [
            p.page_no for p in pages
            if p._backend is not None and p._backend.is_valid()
        ]
        try:
            selected = (
                outlined_text_pages(conv_res.input.file, eligible)
                if eligible else set()
            )
        except Exception as error:
            logger.warning(
                "Outline inspection failed for %s; using normal OCR: %s",
                conv_res.input.file, error,
            )
            selected = set()
        for page in pages:
            if page.page_no not in selected:
                yield from self.standard(conv_res, [page])
                continue
            logger.info(
                "Outlined text detected in %s page %s; using full-page OCR",
                conv_res.input.file.name, page.page_no,
            )
            original = page.parsed_page.model_copy(deep=True)
            original_size = _text_size(page.cells)
            try:
                processed = list(self._full_page_model()(conv_res, [page]))
                if len(processed) != 1 or processed[0] is not page:
                    raise ValueError("OCR did not return the requested page")
                if _text_size(page.cells) < max(1, original_size * 0.5):
                    raise ValueError("OCR returned empty or severely reduced text")
                recognized = list(page.cells)
                page.parsed_page = original.model_copy(deep=True)
                # Keep precise native text (especially numbers and URLs). Reuse
                # Docling's normal overlap filter to add only uncovered OCR cells.
                self.standard.post_process_cells(recognized, page)
            except Exception as error:
                page.parsed_page = original
                logger.warning(
                    "Full-page OCR rejected for %s page %s; "
                    "retaining original text and normal OCR: %s",
                    conv_res.input.file.name, page.page_no, error,
                )
                yield from self.standard(conv_res, [page])
            else:
                yield page


class SelectiveOcrPipeline(StandardPdfPipeline):
    def _make_ocr_model(self, art_path):
        standard = super()._make_ocr_model(art_path)
        options = self.pipeline_options
        if not options.do_ocr or options.ocr_options.force_full_page_ocr:
            return standard

        def full_page_factory():
            return get_ocr_factory(
                allow_external_plugins=options.allow_external_plugins,
            ).create_instance(
                options=options.ocr_options.model_copy(
                    update={"force_full_page_ocr": True},
                ),
                enabled=True,
                artifacts_path=art_path,
                accelerator_options=options.accelerator_options,
            )

        return SelectiveOcrModel(standard, full_page_factory)

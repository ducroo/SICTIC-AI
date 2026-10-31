"""Cheap, conservative detection of text drawn as PDF vector outlines.

No rendering or model calls: inspect path geometry in PDFium. This is a heuristic,
not a font decoder; dense diagrams and logos can still cause extra OCR.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
from docling.utils.locks import pypdfium2_lock


@dataclass(frozen=True)
class VectorShape:
    bounds: tuple[float, float, float, float]
    segments: int


def _page_bounds(obj) -> tuple[float, float, float, float]:
    bounds = obj.get_bounds()
    # Child objects use their containing Form XObject's coordinate system.
    parent = obj.container
    while parent is not None:
        bounds = parent.get_matrix().on_rect(*bounds)
        parent = parent.container
    return bounds


def _covered(bounds, text_bounds) -> bool:
    left, bottom, right, top = bounds
    area = (right - left) * (top - bottom)
    return any(
        max(0, min(right, r) - max(left, l))
        * max(0, min(top, t) - max(bottom, b)) > 0.6 * area
        for l, b, r, t in text_bounds
    )


def has_outlined_text(
    shapes: list[VectorShape],
    text_bounds: list[tuple[float, float, float, float]],
    page_bounds: tuple[float, float, float, float],
) -> bool:
    """Find multiple text-like rows not already represented by text objects."""
    pl, pb, pr, pt = page_bounds
    page_height = pt - pb
    rows = []
    glyphs = []
    for shape in shapes:
        left, bottom, right, top = shape.bounds
        width, height = right - left, top - bottom
        if not (0.006 * page_height <= height <= 0.09 * page_height):
            continue
        # Exclude off-page objects and small marginal copyright/version footers.
        if right <= pl or left >= pr or top <= pb or bottom >= pt:
            continue
        if top < pb + 0.07 * page_height:
            continue
        if width <= 0 or _covered(shape.bounds, text_bounds):
            continue
        aspect = width / height
        if aspect >= 2.5 and shape.segments >= 80:
            rows.append(shape.bounds)
        elif 0.1 <= aspect < 2.5 and shape.segments >= 8:
            glyphs.append(shape.bounds)

    # Some exporters draw each glyph separately rather than a whole text run.
    groups = []
    for box in sorted(glyphs, key=lambda b: b[0]):
        left, bottom, right, top = box
        height = top - bottom
        for group in groups:
            gl, gb, gr, gt, count = group
            gh = gt - gb
            if (
                abs(bottom - gb) <= 0.3 * max(height, gh)
                and 0.5 <= height / gh <= 2
                and -0.1 * height <= left - gr <= 1.2 * height
            ):
                group[:] = [gl, min(gb, bottom), right, max(gt, top), count + 1]
                break
        else:
            groups.append([left, bottom, right, top, 1])
    rows.extend(tuple(g[:4]) for g in groups if g[4] >= 5)

    # Require two distinct lines, so one outlined logo does not trigger OCR.
    baselines = []
    for left, bottom, right, top in rows:
        height = top - bottom
        if all(abs(bottom - y) > 0.5 * min(height, h) for y, h in baselines):
            baselines.append((bottom, height))
    return len(baselines) >= 2


def outlined_text_pages(filepath: str | Path, page_numbers: list[int]) -> set[int]:
    """Inspect only this OCR batch's pages, using original one-based page numbers."""
    selected = set()
    with pypdfium2_lock, pdfium.PdfDocument(filepath) as document:
        for number in page_numbers:
            with closing(document[number - 1]) as page:
                shapes, text_bounds = [], []
                with closing(page.get_textpage()) as textpage:
                    for obj in page.get_objects(textpage=textpage):
                        if obj.type == pdfium.raw.FPDF_PAGEOBJ_PATH:
                            shapes.append(
                                VectorShape(
                                    _page_bounds(obj),
                                    pdfium.raw.FPDFPath_CountSegments(obj),
                                )
                            )
                        elif (
                            obj.type == pdfium.raw.FPDF_PAGEOBJ_TEXT
                            and obj.extract().strip()
                        ):
                            text_bounds.append(_page_bounds(obj))
                if has_outlined_text(shapes, text_bounds, page.get_bbox()):
                    selected.add(number)
    return selected

import pytest

from lib.datasets.text_normalization import (
    has_dense_private_use_encoding,
    normalize_extracted_text,
    requires_text_normalization,
)


def test_rejects_dense_private_use_font_mapping_for_ocr():
    encoded = "".join(
        chr(ord(char) + 0xF002)
        for char in "Approved for use through"
        if char != " "
    )

    assert has_dense_private_use_encoding(encoded)
    with pytest.raises(ValueError, match="requires OCR"):
        normalize_extracted_text(encoded)


def test_replaces_sparse_private_use_and_control_runs_with_spaces():
    text = "before\uf0a7\uf0b7after\x00\x01end\nnext"

    assert requires_text_normalization(text)
    assert normalize_extracted_text(text) == "before after end\nnext"


def test_preserves_general_unicode_and_allowed_whitespace():
    text = "Zürich — 東京 😊\tvalue\r\n"

    assert not requires_text_normalization(text)
    assert normalize_extracted_text(text) == text


def test_rejects_unknown_dense_private_use_encoding():
    text = "".join(chr(0xE100 + index) for index in range(20))

    with pytest.raises(ValueError, match="requires OCR"):
        normalize_extracted_text(text)


@pytest.mark.parametrize(
    "character",
    [
        chr(0xE000),
        chr(0xF0000),
        chr(0x100000),
        chr(0xD800),
        chr(0xFDD0),
        chr(0x1FFFE),
    ],
)
def test_excludes_all_target_character_classes(character):
    assert normalize_extracted_text(f"before{character}after") == "before after"

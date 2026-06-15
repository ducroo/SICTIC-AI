import hashlib
import uuid

from lib.datasets.chunking import split_markdown


def test_split_markdown_generates_stable_chunk_ids():
    text = "This is a test document. " * 100
    filename = "test_file.md"

    chunks = split_markdown(text, filename, 123456789.0)

    assert chunks
    first = chunks[0]
    expected_hash = hashlib.md5(
        f"{filename}_{first.text}".encode("utf-8")
    ).hexdigest()
    assert first.chunk_id == str(uuid.UUID(hex=expected_hash))
    assert first.document_name == filename

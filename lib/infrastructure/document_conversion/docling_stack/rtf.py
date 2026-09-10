def convert_rtf(filepath: str) -> str:
    """Extract searchable text from RTF, which Docling does not support."""
    from striprtf.striprtf import rtf_to_text

    with open(filepath, "r", encoding="latin-1") as handle:
        rtf = handle.read()
    text = rtf_to_text(rtf, errors="replace")
    return text.strip() + "\n" if text.strip() else ""

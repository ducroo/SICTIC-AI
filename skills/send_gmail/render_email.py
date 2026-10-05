"""Render Markdown as a self-contained HTML email, without sending it."""
from pathlib import Path
from tempfile import NamedTemporaryFile

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt


STYLES = {
    "h1": "font-size:24px;line-height:1.3;margin:0 0 20px;",
    "h2": "font-size:20px;line-height:1.3;margin:28px 0 12px;",
    "h3": "font-size:17px;margin:22px 0 10px;",
    "p": "margin:0 0 16px;",
    "ul": "margin:0 0 16px;padding-left:24px;",
    "ol": "margin:0 0 16px;padding-left:24px;",
    "li": "margin:0 0 6px;",
    "a": "color:#1558b0;text-decoration:underline;",
    "table": "border-collapse:collapse;width:100%;margin:16px 0;font-size:14px;",
    "th": "background-color:#f1f4f8;border:1px solid #d8dee6;padding:10px;text-align:left;vertical-align:top;",
    "td": "border:1px solid #d8dee6;padding:10px;text-align:left;vertical-align:top;",
    "blockquote": "margin:16px 0;padding:0 16px;border-left:3px solid #cbd5e1;color:#475569;",
    "pre": "background-color:#f1f4f8;padding:12px;white-space:pre-wrap;overflow-wrap:anywhere;",
    "code": "font-family:Menlo,Consolas,monospace;font-size:13px;background-color:#f1f4f8;",
    "hr": "border:0;border-top:1px solid #d8dee6;margin:24px 0;",
    "img": "max-width:100%;height:auto;",
}


def markdown_to_email(markdown: str) -> str:
    """Keep Markdown structure and add email-compatible inline formatting."""
    rendered = MarkdownIt("commonmark", {"html": False}).enable("table").render(markdown)
    body = BeautifulSoup(rendered, "html.parser")
    for tag in body.find_all(True):
        if style := STYLES.get(tag.name):
            # Preserve Markdown's explicit table-column alignment.
            tag["style"] = style + str(tag.get("style", ""))
    return (
        '<!doctype html><html><head><meta charset="utf-8"></head>'
        '<body style="margin:0;padding:24px;background-color:#ffffff;">'
        '<div style="max-width:760px;margin:0 auto;font-family:Arial,Helvetica,sans-serif;'
        'font-size:16px;line-height:1.6;color:#202124;overflow-wrap:break-word;">'
        f'{body}</div></body></html>\n'
    )


def convert_file(source: Path, output: Path | None = None) -> Path:
    """Write UTF-8 HTML to the selected path or a private temporary file."""
    if output is not None and source.resolve() == output.resolve():
        raise ValueError("The HTML output must differ from the Markdown input.")
    html = markdown_to_email(source.read_text(encoding="utf-8"))
    if output is None:
        with NamedTemporaryFile(mode="w", encoding="utf-8", prefix="sictic-email-", suffix=".html", delete=False) as handle:
            handle.write(html)
            return Path(handle.name)
    output.write_text(html, encoding="utf-8")
    return output.resolve()

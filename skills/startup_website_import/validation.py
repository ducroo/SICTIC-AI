"""Conservative, deterministic checks before a website response becomes evidence."""

import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Comment


def redirect_allowed(requested: str, resolved: str, policy: dict) -> bool:
    """Permit canonical www/HTTPS changes or an explicitly verified host mapping."""
    def host(url):
        return (urlsplit(url).hostname or "").lower().rstrip(".").removeprefix("www.")

    source, target = host(requested), host(resolved)
    if urlsplit(resolved).scheme not in {"http", "https"} or not target:
        return False
    return source == target or target in policy["approved_redirect_hosts"].get(source, [])


def screen_html(html: str, policy: dict) -> tuple[str | None, str | None]:
    """Reject gambling pages; remove only short, isolated spam labels and links.

    Ordinary mentions of gambling/casinos are intentionally not a rejection
    signal. Ambiguous longer spam blocks cause a page skip, not a broad rewrite.
    """
    spam = re.compile("|".join(policy["gambling_spam_patterns"]), re.I)
    promotion = re.compile("|".join(policy["gambling_promotion_heading_patterns"]), re.I)
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.find_all(["script", "style", "noscript", "svg"]):
        node.decompose()
    for node in soup.find_all(string=lambda text: isinstance(text, Comment)):
        node.extract()
    for heading in soup.find_all(["title", "h1"]):
        text = heading.get_text(" ", strip=True)
        if spam.search(text) or promotion.search(text):
            return None, "Gambling promotion in page title or main heading"

    original_length = len(soup.get_text(" ", strip=True))
    removed = 0
    # Inspect hrefs too: a spam link can be labelled merely 'Play'. Removing
    # the anchor here prevents it entering the crawl queue or LinkedIn list.
    for anchor in list(soup.find_all("a", href=True)):
        if spam.search(anchor.get("href", "")) or spam.search(anchor.get_text(" ", strip=True)):
            if len(anchor.get_text(" ", strip=True).split()) > policy["max_spam_label_words"]:
                return None, "Gambling spam cannot be isolated safely"
            anchor.decompose()
            removed += 1
    for text_node in list(soup.find_all(string=True)):
        text = str(text_node).strip()
        if not spam.search(text):
            continue
        # A footer may be one text node containing several bare spam labels.
        # Only strip a longer node if nothing but those labels remains.
        if (len(text.split()) > policy["max_spam_label_words"]
                and spam.sub("", text).strip(" \n\t|,;-")):
            return None, "Gambling spam cannot be isolated safely"
        text_node.extract()
        removed += 1

    if removed:
        clean_length = len(soup.get_text(" ", strip=True))
        if clean_length < policy["minimum_clean_page_characters"] or clean_length < original_length / 2:
            return None, "Page is predominantly gambling spam"
        return str(soup), f"Removed {removed} isolated gambling spam labels/links"
    return html, None

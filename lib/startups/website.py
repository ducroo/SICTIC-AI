"""Select a documented company website without inventing a domain."""

import re
from urllib.parse import urlsplit

from lib.datasets.models import Chunk
from lib.slugify import slugify


def website_from_evidence(company_names: list[str], chunks: list[Chunk]) -> str | None:
    """Prefer company-name domains or explicit website fields; reject ties."""
    names = {slugify(name).replace("-", "") for name in company_names if name}
    candidates: dict[str, int] = {}
    for chunk in chunks:
        for match in re.finditer(r"(?:https?://|www\.)[^\s<>\"'\])]+", chunk.text):
            url = match.group().rstrip(".,;:")
            if url.startswith("www."):
                url = "https://" + url
            parsed = urlsplit(url)
            host = (parsed.hostname or "").lower().removeprefix("www.")
            if not host or any(host == suffix or host.endswith("." + suffix) for suffix in (
                "linkedin.com", "google.com", "youtube.com", "facebook.com", "dealum.com",
                "instagram.com", "twitter.com", "x.com", "sictic.ch",
            )):
                continue
            label = chunk.text[max(0, match.start() - 50):match.start()].casefold()
            company_domain = slugify(host.split(".")[0]).replace("-", "") in names
            labelled = bool(re.search(r"(?:website|webseite|homepage|site web)\s*[:|\-\"\s]*$", label))
            score = 2 * company_domain + labelled
            if score:
                origin = f"{parsed.scheme}://{parsed.netloc}"
                candidates[origin] = max(score, candidates.get(origin, 0))
    if not candidates:
        return None
    best = max(candidates.values())
    winners = [url for url, score in candidates.items() if score == best]
    return winners[0] if len(winners) == 1 else None

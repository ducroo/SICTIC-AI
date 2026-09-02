"""Web search backed by the Apify Google Search Scraper actor."""

from typing import TypedDict

from lib.infrastructure.apify import ApifyAdapter
from lib.infrastructure.logging import get_logger

logger = get_logger(__name__)

_GOOGLE_SEARCH_ACTOR = "apify/google-search-scraper"


class WebSearchResult(TypedDict):
    """Normalized fields returned for an organic search result."""

    title: str
    link: str
    snippet: str


class WebSearchAdapter:
    def __init__(self) -> None:
        self.apify = ApifyAdapter()

    def search(self, query: str, num_results: int = 10) -> list[WebSearchResult]:
        if num_results < 0:
            raise ValueError("num_results must be non-negative")

        try:
            logger.info("Querying Google Search via Apify for: %s", query)
            results = self.apify.run_actor(
                _GOOGLE_SEARCH_ACTOR,
                {
                    "queries": query,
                    "maxPagesPerQuery": 1,
                },
            )

            parsed_results: list[WebSearchResult] = []
            for item in results:
                for result in item.get("organicResults", []):
                    parsed_results.append(
                        {
                            "title": result.get("title") or "",
                            "link": result.get("url") or "",
                            "snippet": result.get("description") or "",
                        }
                    )

            return parsed_results[:num_results]
        except Exception as error:
            logger.error("Web search failed for query %r: %s", query, error)
            raise RuntimeError(f"Web search error: {error}") from error

"""LinkedIn-focused discovery through the shared web search provider."""

from collections.abc import Callable

from lib.datasets.chunking import build_chunk
from lib.infrastructure.errors import InfrastructureError
from lib.infrastructure.web_search import WebSearchAdapter
from lib.people.linkedin.identity import extract_linkedin_ids
from lib.people.model import Person


def search_people(company: str, *, query: str, num_results: int,
                  search: WebSearchAdapter | None = None,
                  on_error: Callable[[InfrastructureError], None] | None = None) -> list[Person]:
    """Discover profile IDs with one company-wide query, never per-person queries."""
    search = search or WebSearchAdapter()
    try:
        results = search.search(query.format(company=company), num_results=num_results)
    except InfrastructureError as error:
        if on_error is None:
            raise
        on_error(error)
        return []
    people = []
    for result in results:
        text = f"{result['title']}\n{result['snippet']}\n{result['link']}"
        chunk = build_chunk(text, result["link"], "n/a", 0)
        for identifier in extract_linkedin_ids(text):
            people.append(Person(linkedin_id=identifier, mentions=[chunk]))
    return people

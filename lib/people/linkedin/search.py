"""LinkedIn-focused discovery through the shared web search provider."""

from collections.abc import Callable

from lib.datasets.chunking import build_chunk
from lib.infrastructure.errors import InfrastructureError
from lib.infrastructure.configuration import load_repository_config
from lib.infrastructure.web_search import WebSearchAdapter
from lib.people.linkedin.identity import extract_linkedin_ids
from lib.people.model import Person


def search_people(company: str, names: list[str], *, queries: list[str], num_results: int,
                  search: WebSearchAdapter | None = None, name_query: str | None = None,
                  on_error: Callable[[InfrastructureError], None] | None = None) -> list[Person]:
    """Keep unverified profile candidates and search evidence for reconciliation."""
    search = search or WebSearchAdapter()
    searches = [query.format(company=company) for query in queries]
    if names:
        if name_query is None:
            name_query = load_repository_config("persons_in_dataset", "discovery")["search"]["linkedin_name_query"]
        searches.extend(name_query.format(name=name, company=company) for name in dict.fromkeys(names))
    people = []
    for query in dict.fromkeys(searches):
        try:
            results = search.search(query, num_results=num_results)
        except InfrastructureError as error:
            if on_error is None:
                raise
            on_error(error)
            continue
        for result in results:
            text = f"{result['title']}\n{result['snippet']}\n{result['link']}"
            chunk = build_chunk(text, result["link"], "n/a", 0)
            for identifier in extract_linkedin_ids(text):
                people.append(Person(linkedin_id=identifier, mentions=[chunk]))
    return people

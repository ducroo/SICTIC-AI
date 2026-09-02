import pytest

from lib.infrastructure.web_search import WebSearchAdapter


class _FakeApifyAdapter:
    def __init__(self, results=None, error=None):
        self.results = results or []
        self.error = error
        self.calls = []

    def run_actor(self, actor_id, run_input):
        self.calls.append((actor_id, run_input))
        if self.error is not None:
            raise self.error
        return self.results


def _adapter(apify):
    adapter = WebSearchAdapter.__new__(WebSearchAdapter)
    adapter.apify = apify
    return adapter


def test_search_normalizes_and_limits_organic_results():
    apify = _FakeApifyAdapter(
        [
            {
                "organicResults": [
                    {
                        "title": "First",
                        "url": "https://example.com/first",
                        "description": "First result",
                    },
                    {
                        "title": "Second",
                        "url": "https://example.com/second",
                        "description": None,
                    },
                    {
                        "title": "Third",
                        "url": "https://example.com/third",
                        "description": "Excluded by the limit",
                    },
                ]
            }
        ]
    )

    results = _adapter(apify).search("example", num_results=2)

    assert results == [
        {
            "title": "First",
            "link": "https://example.com/first",
            "snippet": "First result",
        },
        {
            "title": "Second",
            "link": "https://example.com/second",
            "snippet": "",
        },
    ]
    assert apify.calls == [
        (
            "apify/google-search-scraper",
            {"queries": "example", "maxPagesPerQuery": 1},
        )
    ]


def test_search_rejects_negative_result_limit():
    with pytest.raises(ValueError, match="num_results must be non-negative"):
        _adapter(_FakeApifyAdapter()).search("example", num_results=-1)


def test_search_preserves_provider_error_as_cause():
    provider_error = RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError, match="Web search error") as exc_info:
        _adapter(_FakeApifyAdapter(error=provider_error)).search("example")

    assert exc_info.value.__cause__ is provider_error

from lib.datasets.chunking import build_chunk
from lib.startups.website import website_from_evidence


def test_website_must_be_documented_and_social_links_are_excluded():
    chunks = [build_chunk("Website: https://acme.example/team\nhttps://linkedin.com/company/acme/", "application.md", 1, 0)]
    assert website_from_evidence(["acme"], chunks) == "https://acme.example"
    assert website_from_evidence(["unknown"], []) is None


def test_ambiguous_website_fields_do_not_choose_arbitrarily():
    chunks = [build_chunk("Website: https://one.example\nWebsite: https://two.example", "application.md", 1, 0)]
    assert website_from_evidence(["acme"], chunks) is None

from lib.datasets.source import list_source_files


class FakeStorage:
    def list_with_mtime(self, rel, *, recursive=False):
        return [
            ("application.md", 1.0),
            ("dealum/documents/deck.pdf", 2.0),
            ("dealum/documents/logo.svg", 3.0),
            ("dealum/documents/screenshot.PNG", 4.0),
            ("dealum/manifest.json", 5.0),
            ("dealum/application.raw.json", 6.0),
            ("linkedin/founder.json", 7.0),
        ]


def test_list_source_files_ignores_assets_and_metadata():
    files = list_source_files(FakeStorage(), "storage/startups/bewe/datasets")

    names = [name for name, _ in files]
    assert names == [
        "application.md",
        "dealum/documents/deck.pdf",
        "linkedin/founder.json",
    ]

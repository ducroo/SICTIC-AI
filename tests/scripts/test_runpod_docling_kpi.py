from __future__ import annotations

from scripts.runpod_docling_kpi import (
    MINIMAL_PDF,
    QUALITY_CONVERT_OPTIONS,
    collect_base_urls,
    convert_form_fields,
    extract_convert_payload,
    estimated_usd,
    linearized_page_count,
    load_input_document,
    parse_args,
    parse_json_content,
    probe_ready,
    proxy_url,
    rank_gpu_candidates,
    summarize_docling_graph,
    build_convert_options,
)


CATALOG = [
    {
        "id": "Tesla V100-PCIE-16GB",
        "memory": 16,
        "community": True,
        "secure": False,
        "availability": "LOW",
        "price": {"community": 0.19},
        "dataCenters": [],
    },
    {
        "id": "NVIDIA RTX A5000",
        "memory": 24,
        "community": True,
        "secure": True,
        "availability": "NONE",
        "price": {"community": 0.16, "secure": 0.27},
        "dataCenters": [],
    },
    {
        "id": "NVIDIA RTX A4500",
        "memory": 20,
        "community": True,
        "secure": True,
        "availability": "LOW",
        "price": {"community": 0.19, "secure": 0.25},
        "dataCenters": [],
    },
    {
        "id": "NVIDIA GeForce RTX 3090",
        "memory": 24,
        "community": True,
        "secure": True,
        "availability": "LOW",
        "price": {"community": 0.22, "secure": 0.5},
        "dataCenters": [{"id": "EU-CZ-1", "availability": "LOW"}],
    },
    {
        "id": "NVIDIA GeForce RTX 3070",
        "memory": 8,
        "community": True,
        "secure": False,
        "availability": "LOW",
        "price": {"community": 0.13},
        "dataCenters": [],
    },
]


def test_rank_gpu_candidates_skips_v100_low_vram_and_empty_stock():
    ranked = rank_gpu_candidates(CATALOG)

    assert [item["id"] for item in ranked] == [
        "NVIDIA RTX A4500",
        "NVIDIA GeForce RTX 3090",
    ]
    assert ranked[0]["price"] == 0.19
    assert ranked[1]["data_center_ids"] == ["EU-CZ-1"]


def test_collect_base_urls_prefers_proxy_then_direct_port():
    pod = {
        "id": "abc123",
        "runtime": {
            "ports": [
                {"private": 22, "public": 10022, "type": "tcp", "ip": "1.2.3.4"},
                {"private": 5001, "public": 15001, "type": "tcp", "ip": "1.2.3.4"},
            ]
        },
    }

    assert proxy_url("abc123") == "https://abc123-5001.proxy.runpod.net"
    assert collect_base_urls(pod) == [
        "https://abc123-5001.proxy.runpod.net",
        "http://1.2.3.4:15001",
    ]


def test_estimated_usd_uses_hourly_rate_over_elapsed_seconds():
    assert estimated_usd(0.22, 180) == 0.011
    assert estimated_usd(None, 180) is None


class _FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


def test_probe_ready_ignores_proxy_404_and_accepts_docs_200(monkeypatch):
    statuses = {
        "/health": 404,
        "/docs": 200,
        "/openapi.json": 404,
        "/ui": 404,
    }

    class _FakeSession:
        headers: dict[str, str] = {}

        def get(self, url, timeout=8.0, allow_redirects=True):
            path = "/" + url.rsplit("/", 1)[-1]
            if url.endswith("/openapi.json"):
                path = "/openapi.json"
            return _FakeResponse(statuses[path])

    monkeypatch.setattr("scripts.runpod_docling_kpi.requests.Session", lambda: _FakeSession())
    ok, detail, status = probe_ready("https://abc-5001.proxy.runpod.net")
    assert ok is True
    assert status == 200
    assert detail == "/docs 200"


def test_load_input_document_reads_pdf_and_linearized_page_hint(tmp_path):
    header = b"%PDF-1.6\n1 0 obj<</Linearized 1/L 100/O 2/E 10/N 15/T 90>>endobj\n"
    pdf = tmp_path / "deck.pdf"
    pdf.write_bytes(header + b"%EOF\n")

    filename, data, meta = load_input_document(pdf)

    assert filename == "deck.pdf"
    assert data.startswith(b"%PDF")
    assert meta["bytes"] == len(header) + 5
    assert meta["pages_hint"] == 15
    assert linearized_page_count(MINIMAL_PDF) is None


def test_quality_profile_requests_json_graph_and_accurate_tables():
    args = parse_args(["--quality", "--input", "deck.pdf", "--convert-timeout", "900"])
    options = build_convert_options(args)
    fields = convert_form_fields(options)

    assert options["to_formats"] == ["json", "md", "html"]
    assert options["table_mode"] == "accurate"
    assert options["do_pdf_heading_hierarchy"] is True
    assert "do_chart_extraction" not in options
    assert ("to_formats", "json") in fields
    assert ("table_mode", "accurate") in fields
    assert options.keys() >= QUALITY_CONVERT_OPTIONS.keys()


def test_extract_convert_payload_reads_json_and_markdown():
    markdown, html, graph, errors = extract_convert_payload(
        {
            "document": {
                "md_content": "# Title",
                "html_content": "<h1>Title</h1>",
                "json_content": {"schema_name": "DoclingDocument", "texts": [{}]},
            },
            "errors": [],
        }
    )
    assert markdown == "# Title"
    assert html.startswith("<h1>")
    assert graph is not None
    assert graph["schema_name"] == "DoclingDocument"
    assert errors == []


def test_summarize_docling_graph_counts_tables_and_pages():
    graph = {
        "schema_name": "DoclingDocument",
        "name": "deck",
        "body": {"self_ref": "#/body"},
        "pages": {"1": {}, "2": {}},
        "texts": [{}, {}],
        "tables": [{"label": "table", "data": {"grid": [[{}, {}], [{}, {}]]}}],
        "pictures": [{"label": "picture", "classifications": [{"class_name": "chart"}]}],
        "groups": [{}],
    }
    summary = summarize_docling_graph(graph)
    assert summary["pages"] == 2
    assert summary["tables"] == 1
    assert summary["table_shapes"] == [{"rows": 2, "cols": 2, "label": "table"}]
    assert summary["pictures"] == 1
    assert parse_json_content('{"schema_name":"DoclingDocument"}')["schema_name"] == (
        "DoclingDocument"
    )


def test_load_input_document_falls_back_to_builtin_smoke_pdf():
    filename, data, meta = load_input_document(None)
    assert filename == "smoke.pdf"
    assert data == MINIMAL_PDF
    assert meta["pages_hint"] == 1


def test_probe_ready_ignores_health_200_without_docs(monkeypatch):
    class _FakeSession:
        headers: dict[str, str] = {}

        def get(self, url, timeout=8.0, allow_redirects=True):
            path = "/" + url.rsplit("/", 1)[-1]
            if url.endswith("/openapi.json"):
                path = "/openapi.json"
            return _FakeResponse(200 if path == "/health" else 404)

    monkeypatch.setattr("scripts.runpod_docling_kpi.requests.Session", lambda: _FakeSession())
    ok, detail, status = probe_ready("http://1.2.3.4:5001")
    assert ok is False
    assert status is None
    assert "404" in detail


def test_probe_ready_stays_unready_when_every_route_is_404(monkeypatch):
    class _FakeSession:
        headers: dict[str, str] = {}

        def get(self, url, timeout=8.0, allow_redirects=True):
            return _FakeResponse(404)

    monkeypatch.setattr("scripts.runpod_docling_kpi.requests.Session", lambda: _FakeSession())
    ok, detail, status = probe_ready("https://abc-5001.proxy.runpod.net")
    assert ok is False
    assert status is None
    assert detail.endswith("404")

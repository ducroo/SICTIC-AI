from __future__ import annotations

from scripts import docling_graph_markdown as script
from lib.infrastructure.document_conversion.graph_markdown import graph_to_markdown


GRAPH = {
    "body": {
        "children": [
            {"$ref": "#/texts/0"},
            {"$ref": "#/groups/0"},
            {"$ref": "#/tables/0"},
            {"$ref": "#/pictures/0"},
        ]
    },
    "texts": [
        {
            "label": "section_header",
            "level": 1,
            "text": "Selected financials",
            "prov": [{"page_no": 2}],
        },
        {
            "label": "text",
            "text": "14.4%",
            "prov": [{"page_no": 1}],
        },
        {
            "label": "text",
            "text": "CET1 capital ratio",
            "prov": [{"page_no": 1}],
        },
        {"label": "page_header", "text": "Media Relations", "prov": [{"page_no": 1}]},
    ],
    "groups": [
        {
            "label": "key_value_area",
            "children": [{"$ref": "#/texts/1"}, {"$ref": "#/texts/2"}],
            "prov": [{"page_no": 1}],
        }
    ],
    "tables": [
        {
            "data": {
                "grid": [
                    [{"text": "USD m"}, {"text": "GWM"}],
                    [{"text": "Revenue"}, {"text": "7,112"}],
                ]
            },
            "prov": [{"page_no": 2}],
        }
    ],
    "pictures": [{"label": "picture", "prov": [{"page_no": 2}]}],
}


def test_graph_to_markdown_emits_page_markers_tables_and_kpi_pairs():
    markdown = graph_to_markdown(GRAPH)

    assert "<!-- sictic-page:2 -->" in markdown
    assert "# Selected financials" in markdown
    assert "| CET1 capital ratio | 14.4% |" in markdown
    assert "| USD m | GWM |" in markdown
    assert "| Revenue | 7,112 |" in markdown
    assert "<!-- figure page 2 -->" in markdown
    assert "Media Relations" not in markdown


def test_script_reexports_lib_renderer():
    assert script.graph_to_markdown is graph_to_markdown

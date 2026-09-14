from __future__ import annotations

from scripts.runpod_docling_kpi import (
    collect_base_urls,
    estimated_usd,
    probe_ready,
    proxy_url,
    rank_gpu_candidates,
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

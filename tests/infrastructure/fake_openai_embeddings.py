"""OpenAI-shaped embeddings stand-in for local demo runs."""

from __future__ import annotations

import hashlib
import os

from aiohttp import web

VECTOR_SIZE = 8


def embed_text(text: str) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values = [b / 255.0 for b in digest[:VECTOR_SIZE]]
    return values


def create_app() -> web.Application:
    app = web.Application()
    app.add_routes(
        [
            web.post("/embeddings", _handle_embeddings),
            web.post("/v1/embeddings", _handle_embeddings),
        ]
    )
    return app


async def _handle_embeddings(request: web.Request) -> web.Response:
    body = await request.json()
    raw = body.get("input")
    if isinstance(raw, str):
        texts = [raw]
    elif isinstance(raw, list):
        texts = [str(item) for item in raw]
    else:
        return web.json_response({"error": "input required"}, status=400)
    model = str(body.get("model") or "sictic-test-embed")
    data = [
        {"object": "embedding", "index": index, "embedding": embed_text(text)}
        for index, text in enumerate(texts)
    ]
    return web.json_response(
        {
            "object": "list",
            "model": model,
            "data": data,
            "usage": {"prompt_tokens": 0, "total_tokens": 0},
        }
    )


def main() -> None:
    port = int(os.environ.get("PORT") or "8009")
    web.run_app(create_app(), host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()

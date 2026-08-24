# LlamaParse + Firestore spike  # pragma: allowlist secret

Experimental backends for dataset ingestion and semantic search. Defaults stay
`DOCUMENT_PARSER=docling` and `VECTOR_STORE=qdrant`. Cloud Agent `install`/`start`
auto-select `llamaparse` / `firestore` when `LLAMA_CLOUD_API_KEY` and Firebase secrets are present unless you override those two vars explicitly. <!-- pragma: allowlist secret -->

## Enable the spike

```bash
# .env (or Cloud Agent secrets)
DOCUMENT_PARSER=llamaparse  # pragma: allowlist secret
LLAMA_CLOUD_API_KEY=llx-...
LLAMA_PARSE_TIER=cost_effective   # optional: agentic | cost_effective | fast
VECTOR_STORE=firestore  # pragma: allowlist secret
FIREBASE_PROJECT_ID=your-project-id
FIREBASE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
# Optional. Firestore KNN max dimension is 2048. Default 1536.  # pragma: allowlist secret
# FIRESTORE_EMBEDDING_DIMENSIONS=1536  # pragma: allowlist secret
```

Do not put `FIREBASE_SERVICE_ACCOUNT_JSON` in `.env` on Cloud Agents. `start`
writes it to `~/.openclaw/firebase-service-account.json` and sets
`GOOGLE_APPLICATION_CREDENTIALS`. `sed` would corrupt the PEM `\n` sequences.

Cloud Agent `start` skips local Qdrant when `VECTOR_STORE=firestore`.  # pragma: allowlist secret

## What changed

| Concern | Default | Spike |
|---|---|---|
| Parse | `DoclingAdapter` (local) | `LlamaParseAdapter` via LlamaCloud | <!-- pragma: allowlist secret -->
| Vectors | `QdrantAdapter` (local) | `FirestoreAdapter` (`find_nearest`, cosine) | <!-- pragma: allowlist secret -->
| Selection | env factories in `lib/adapters/document_parser.py` and `lib/adapters/vector_store.py` | same |

Call sites (`conversion`, `indexing`, `search`, ephemeral datasets, maintenance)
go through the factories. Spreadsheet/RTF/plain-text passthrough still runs
locally in the LlamaParse adapter to avoid paying for trivial formats. <!-- pragma: allowlist secret -->

## Firestore notes  # pragma: allowlist secret

The configured Firebase project already has a Standard Native `(default)`
database in `eur3`. Client SDK rules stay locked down; the server SDK used by
this adapter bypasses them.

Standard edition KNN rejects vectors larger than 2048. Cloud Agent embeddings
often use `text-embedding-3-large` (3072). When `VECTOR_STORE=firestore`,  # pragma: allowlist secret
`EmbeddingService` passes `dimensions=1536` (or `FIRESTORE_EMBEDDING_DIMENSIONS`) <!-- pragma: allowlist secret -->
into the embedding request. `ensure_collection` creates a cosine/flat index on
`chunks.embedding` if one is missing. Index builds can take several minutes the
first time.

Collection path: `{dataset-model}/index/chunks`.

## Parser cache note

Parsed Markdown still lands under `docling_data/`. When switching parsers, clear
that cache (or bump `PARSER_VERSION` in `lib/datasets/manifest.py`) so documents
are re-parsed.

## Live check (after secrets)

```bash
conda run -n sictic-env python -m skills.dataset_chat sync <dataset>
conda run -n sictic-env python -m skills.dataset_chat search <dataset> "what does the company do?"
```

## Container

The Dockerfile is `spike/Dockerfile`. It lives under `spike/` so `install.sh` never treats it as the Conda installer path. The image is pip-only and omits torch, Docling, Qdrant, and Ollama. Image defaults are the SaaS parser and Firestore vector store. Host Conda defaults stay `docling` / `qdrant`.  <!-- pragma: allowlist secret -->

Build from the repository root so `lib/`, `skills/`, and `config/` copy into the image.

```bash
docker build -f spike/Dockerfile -t sictic-spike .
docker run --rm -p 8080:8080 \
  -e LLAMA_CLOUD_API_KEY \
  -e FIREBASE_PROJECT_ID \
  -e FIREBASE_SERVICE_ACCOUNT_JSON \
  -e LLM_API_KEY -e EMBEDDING_API_KEY \
  -e LLM_MODEL -e EMBEDDING_MODEL \
  sictic-spike
```

Pass secrets as process environment. Do not copy a `.env` into the image. `lib/env.py` loads repo-root `.env` with `override=True`, so empty template keys would wipe those values. Do not put `FIREBASE_SERVICE_ACCOUNT_JSON` in a file that `sed` will rewrite.

The process binds `0.0.0.0` and reads `PORT` (default 8080). Cloud Run sets `PORT`. `GET /healthz` reports parser, store, and secret presence flags. It does not call LlamaCloud or Firestore. `GET /` is a private demo form that calls `prepare_ephemeral_dataset` and `dataset_search`. There is no auth. Do not publish this port. <!-- pragma: allowlist secret -->

Skills ship in the image as `python -m skills.<name>` with `PYTHONPATH=/app`. The page lists those modules. It does not wrap every Typer CLI.

If `docker build` fails with overlayfs `invalid argument`, prove the process with `conda run -n sictic-env python -m pytest tests/spike/test_runtime.py` and `spike/verify.sh`.

## Hosting emulator

The static UI lives in `hosting/public`. `firebase.json` rewrites `/api/**` to the `spikeGateway` Function, which forwards JSON to the Python process (`POST /api/demo`, `GET /api/status`). Do not start a database emulator. The Python process keeps using the production vector store.

```bash
conda run -n sictic-env python -m spike.web
SPIKE_URL=http://127.0.0.1:8080 bash spike/emulate.sh
```

Hosting emulator: `http://127.0.0.1:5000`. Functions emulator: `http://127.0.0.1:5001`. The Function does not verify Firebase Auth yet. Do not deploy this gateway until it checks ID tokens.

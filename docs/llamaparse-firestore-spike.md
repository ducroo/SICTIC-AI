# LlamaParse + Firestore spike

Experimental backends for dataset ingestion and semantic search. Defaults stay
`DOCUMENT_PARSER=docling` and `VECTOR_STORE=qdrant`. Flip the env vars below to
try SaaS LlamaParse and Firestore vector search without removing the local path.

Cloud Agent `install`/`start` auto-select `llamaparse` / `firestore` when
`LLAMA_CLOUD_API_KEY` and Firebase secrets are present (unless you override
`DOCUMENT_PARSER` / `VECTOR_STORE` explicitly).

## Enable the spike

```bash
# .env (or Cloud Agent secrets)
DOCUMENT_PARSER=llamaparse
LLAMA_CLOUD_API_KEY=llx-...
LLAMA_PARSE_TIER=cost_effective   # optional: agentic | cost_effective | fast
VECTOR_STORE=firestore
FIREBASE_PROJECT_ID=your-project-id
FIREBASE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
```

Cloud Agent `start` skips local Qdrant when `VECTOR_STORE=firestore`.

## What changed

| Concern | Default | Spike |
|---|---|---|
| Parse | `DoclingAdapter` (local) | `LlamaParseAdapter` via LlamaCloud |
| Vectors | `QdrantAdapter` (local) | `FirestoreAdapter` (`find_nearest`, cosine) |
| Selection | env factories in `lib/adapters/document_parser.py` and `lib/adapters/vector_store.py` | same |

Call sites (`conversion`, `indexing`, `search`, ephemeral datasets, maintenance)
go through the factories. Spreadsheet/RTF/plain-text passthrough still runs
locally in the LlamaParse adapter to avoid paying for trivial formats.

## Open questions this spike answers

1. Does LlamaParse Markdown + page markers feed the existing chunker well enough?
2. Is Firestore vector KNN latency/quality acceptable vs Qdrant for SICTIC datasets?
3. Can we drop Docling/torch and the local Qdrant binary from Cloud Agent images?

## Firestore vector index

Firestore requires a vector index on the `embedding` field under each dataset
collection path:

`{collection}/index/chunks`

If `find_nearest` fails, create the index Firestore suggests (gcloud / Firebase
console). Dimension must match `EMBEDDING_MODEL`.

## Parser cache note

Parsed Markdown still lands under `docling_data/`. When switching parsers, clear
that cache (or bump `PARSER_VERSION` in `lib/datasets/manifest.py`) so documents
are re-parsed.

## Live check (after secrets)

```bash
conda run -n sictic-env python -m skills.dataset_chat sync <dataset>
conda run -n sictic-env python -m skills.dataset_chat search <dataset> "what does the company do?"
```

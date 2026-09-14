# RunPod as a hosted convert / embed / LLM backend

Spike notes for using [RunPod](https://www.runpod.io/) instead of local Docling,
local Ollama, or a LlamaIndex-hosted stack. This is not a LlamaIndex product.
It is GPU rental plus official Serverless workers that speak OpenAI-shaped HTTP.

## MCP

RunPod ships two MCP servers. Docs: https://docs.runpod.io/get-started/mcp-servers

| Server | URL | Auth | What it does |
|---|---|---|---|
| Docs | `https://docs.runpod.io/mcp` | none | Search and read public docs |
| API | `https://mcp.getrunpod.io/` or `npx -y @runpod/mcp-server@latest` | OAuth or `RUNPOD_API_KEY` | Create and manage Pods, endpoints, templates, volumes |

`npx @runpod/mcp-server@latest add` is an interactive installer. It writes
Cursor / Claude / VS Code config and then opens a browser for "Sign in with
RunPod". This Cloud Agent VM cannot finish that flow.

This repo therefore pins the hosted URLs in `.cursor/mcp.json`. Cursor Desktop
picks that up after a reload. A Cloud Agent run only sees those servers after
the environment allows them and, for the API server, after a RunPod key or
OAuth session exists.

The API MCP manages infrastructure. It does not parse PDFs or run skills.

## What exists on the Hub (2026-09-14)

Official Serverless workers, both OpenAI-compatible:

- [vLLM](https://console.runpod.io/hub/runpod-workers/worker-vllm) (`runpod-workers/worker-vllm`). Chat completions. ~50k deploys.
- [Infinity Embedding](https://console.runpod.io/hub/runpod-workers/worker-infinity-embedding). Embeddings and rerank. Set `MODEL_NAMES`.

Closest Docling stand-in is a community **Pod**, not a Serverless worker:

- [Docling Serve OCR Nvidia Cuda 12.8](https://console.runpod.io/hub/template/qgrb3e19va). Image `quay.io/docling-project/docling-serve-cu128`. UI on `:5001/ui`, OpenAPI on `:5001/docs`. The template warns that RunPod's shared HTTP proxy kills jobs at 90 seconds, so they want a direct TCP connection to the pod IP.

A second community Pod, `docling-ui`, uses `quay.io/docling-project/docling-serve-cu124`.

Community Serverless OCR exists (EasyOCR, PaddleOCR, GLM-OCR, RolmOCR). PaddleOCR
advertises Markdown. None of these are official `runpod-workers` repos.

There is no official Marker, MinerU, Unstructured, or LlamaIndex Hub worker.
There is no first-party `worker-docling`.

A third-party pattern for VLM parse is `ibm-granite/granite-docling-258M`
(`untied` revision) on top of `runpod/worker-v1-vllm`. That is page-image to
markup, not the full Docling convert stack we already wrap.

## How this would map onto SICTIC

Keep `convert_document` and `EmbeddingService`. Point them at HTTP backends.

| Today | RunPod candidate |
|---|---|
| `DOCUMENT_CONVERTER=docling_stack` in-process | `DOCUMENT_CONVERTER=docling_serve` against a Docling Serve Pod, or a custom Serverless wrapper around `docling-serve` |
| `DOCUMENT_PARSER` SaaS parse | Same convert HTTP, or granite-docling on vLLM for PDFs only |
| `EMBEDDING_*` OpenAI / OpenRouter / Ollama | Infinity Embedding, `https://api.runpod.ai/v2/<id>/openai/v1` |
| `LLM_*` | vLLM worker, same OpenAI client shape |
| `RERANK_*` | Infinity Embedding rerank route |

LlamaIndex itself stays out of the picture. We already own chunking, manifests,
and search. RunPod would replace the GPU-heavy convert and model endpoints,
not the dataset pipeline.

## Community Docling Serve KPI

`scripts/runpod_docling_kpi.py` creates Hub template `qgrb3e19va`
(`quay.io/docling-project/docling-serve-cu128`) on community cloud, converts a
one-page PDF twice, then terminates the pod. It always terminates, including on
failure. The token stays in `.env.runpod` and is gitignored.

Live run on 2026-09-14 (UTC). Community `NVIDIA RTX A4500` at `$0.19/hr`, 64 GB
container disk, no network volume. The cheapest listed GPU (`A4000` at `$0.17`)
had no stock.

| KPI | Measured |
|---|---|
| Create accepted | 1.9 s |
| API `RUNNING` | 0.0 s after create (this is desired state, not a listening container) |
| HTTP ready (`/health` 200 on public TCP) | 259 s from create, 255 s after the `RUNNING` flag |
| Docling cold convert (1-page text PDF) | 4.38 s, 200, markdown `## SICTIC cloud smoke test` |
| Docling warm convert (same file) | 2.35 s |
| Terminate accepted | 0.72 s (`204`) |
| Pod gone | 0.0 s after that |
| Leftover pods / network volumes | none |
| Billed window | 267 s, about `$0.014` |

The shared HTTP proxy (`{podId}-5001.proxy.runpod.net`) stayed `404` for the
whole run. The convert went to the public IP on the mapped TCP port, which
matches the template's 90-second proxy warning. v2 `runtime` was `null` until
that public port appeared, around 4 minutes in. That gap is image pull plus
process start, and it is almost the entire bill.

An earlier attempt treated a proxy `404` as ready, failed the convert, and
terminated in a few seconds. That pod is also gone.

Cheap path for this template. Do not attach a network volume. Talk to the pod
IP, not the proxy. Start the pod only for a batch, then terminate. Leaving it
idle costs `$0.19` every hour and buys nothing once convert is 2 to 4 seconds.

Second live run, same day, larger file. `2q26-media-release-en.pdf` is a 15-page
UBS 2Q26 media release, 643 KB. OCR on, `table_mode=fast`. Community
`NVIDIA RTX 4000 SFF Ada Generation` at `$0.18/hr`.

| KPI | Measured |
|---|---|
| Create accepted | 1.0 s |
| HTTP ready on public TCP | 284 s |
| Docling cold convert | 18.94 s, 200, 526,149 markdown chars |
| Docling warm convert | 16.80 s |
| Terminate / gone | 0.67 s / immediate |
| Leftover pods / network volumes | none |
| Billed window | 323 s, about `$0.016` |

The markdown is at `/opt/cursor/artifacts/docling-kpi-large/2q26-media-release-en.md`
next to the PDF. Most of the 526 KB is 22 embedded page images. A text-only
sidecar is `2q26-media-release-en.text-only.md`. Convert is still seconds. Bring-up
is still the bill.

Third live run, same PDF, quality profile. Community `NVIDIA RTX A4000` at
`$0.17/hr`. Image was already on the host, so bring-up was 23 s. Convert used
async poll. Options were `to_formats=json,md,html`, `do_ocr=true`,
`table_mode=accurate`, `do_table_structure=true`,
`do_pdf_heading_hierarchy=true`, `image_export_mode=placeholder`. Chart
extraction and picture classification failed in 4 s on this image. Skip them.

| KPI | Measured |
|---|---|
| Create accepted | 1.5 s |
| HTTP ready (`/docs` 200) | 23 s |
| Docling quality convert | 18.0 s, 200 |
| JSON graph | 15 pages, 390 texts, 7 tables, 22 pictures |
| Terminate / gone | 0.77 s / immediate |
| Billed window | 54 s, about `$0.003` |

The graph is the useful artifact. Markdown still flattens the cover KPI tiles.
The JSON keeps table grids (including an 8-column revenue split and a 40-row
table), section headers, and picture bounding boxes. Reload
`DoclingDocument` on CPU later. No GPU needed after this file exists.

Files are under `/opt/cursor/artifacts/docling-kpi-quality/`.

## On-demand replacement map

LlamaIndex is not the product. We already own chunking (`split_markdown`),
search, manifests, and skills. RunPod replaces the three paid/GPU endpoints
a startup upload needs: convert, embed, generate.

Middleware first. `convert_document` still returns Markdown. The JSON graph
is the stored source. `lib/infrastructure/document_conversion/graph_markdown.py`
walks `body` children on CPU and emits:

- `<!-- sictic-page:N -->` so the existing chunker keeps page ids
- Markdown tables from `tables[].data.grid`
- Metric tables from `key_value_area` groups (the cover KPI tiles)
- Figure placeholders with page numbers
- Dropped page headers and footers

`scripts/docling_graph_markdown.py` stays as a CLI over that module.

Do not send raw Docling JSON to the LLM. Skills already consume Markdown and
tables. Keep `DocumentConversion.markdown`. The `docling_serve` converter
writes `{filename}.docling.json` next to the source so we can re-render
without another GPU pass.

## Stage 1. Convert through Docling Serve

Set `DOCUMENT_PARSER=docling` and `DOCUMENT_CONVERTER=docling_serve`. Point
`DOCLING_SERVE_URL` at a running Docling Serve, including a community Pod
brought up by `scripts/runpod_docling_kpi.py`. Spreadsheets, RTF, and
`.md`/`.txt`/`.json` still convert locally. The spike image still does not
install Docling. It only speaks HTTP.

Bring up a pod, convert, then terminate. Do not leave the GPU running.
Optional `DOCLING_SERVE_TIMEOUT` is seconds, default 300.

The hosting SPA and `POST /api/demo` accept a file as JSON
`{query, filename, content_base64}` so the existing Function gateway can
forward it. Markdown paste still works. The Python form at `/demo` still
posts multipart.

Pytest covers the path with `tests/infrastructure/fake_docling_serve.py`.
That stand-in is also runnable as a local HTTP server.

`lib.model_config.llm_endpoint` and `embedding_endpoint` already take
`LLM_BASE_URL` / `EMBEDDING_BASE_URL`. A RunPod OpenAI URL is a config change,
not a new client.

| Step | Today | RunPod option | Product | GPU | On-demand shape |
|---|---|---|---|---|---|
| 1. Convert | SaaS parse or in-process Docling | Community Pod `qgrb3e19va` | Pod, not Serverless | 16–24 GB (A4000 / A4500 / 3090) | Create, convert the pack, terminate. ~4 min cold image, ~18 s/15-page PDF, ~$0.17–0.22/hr |
| 1b. Convert later | same | Custom Serverless worker around `docling-serve` | We would build this | 16–24 GB | `workersMin=0`. FlashBoot. No official `worker-docling` yet |
| 2. Embed | OpenRouter / OpenAI | [Infinity Embedding](https://console.runpod.io/hub/runpod-workers/worker-infinity-embedding) | Official Serverless | 8–24 GB | Scale to zero. `https://api.runpod.ai/v2/<id>/openai/v1`. Set `MODEL_NAMES`. Match the stored vector width |
| 2b. Rerank | `RERANK_*` | Same Infinity worker | Official Serverless | same | Infinity rerank route |
| 3. Skills LLM | OpenRouter / OpenAI | [vLLM](https://console.runpod.io/hub/runpod-workers/worker-vllm) | Official Serverless | 24 GB for ~8B, 48 GB for ~32B, 80 GB for ~70B | Scale to zero. Same OpenAI chat client. Pick one model that can emit skill JSON |

Do not put convert, embed, and the LLM on one fat Pod. They have different
lifetimes. Convert is bursty and dies after the upload. Embed and generate
should scale from zero per request.

A single always-on A6000 with all three processes is simpler and wastes
money. Community idle is still $0.17+/hr with no work.

Startup upload flow:

1. Create the Docling Pod (or hit a future convert worker).
2. Convert each file to JSON. Run the CPU walker. Index Markdown.
3. Terminate the convert Pod.
4. Embed chunks on Infinity.
5. Run the requested skills on vLLM.
6. Let embed/LLM workers scale to zero.

Cold start is the tax. Convert image pull is ~4 minutes the first time on a
host, ~20 seconds when the image is warm. Serverless vLLM/Infinity cold
starts are seconds, not minutes, if the worker image is cached. FlashBoot
and a baked or network-volume model help.

Embedding width is a contract. The SaaS spike stores 1536-d vectors with a
2048 cap. Pick an Infinity model that matches, or change the stored size on
purpose. Do not silently swap a 1024-d model onto those indexes.

## Open questions

- Pay for an always-on Docling Serve GPU pod, or wrap `docling-serve` as a
  Serverless load-balancer worker so jobs can exceed 90 seconds.
- Whether `granite-docling` on vLLM is good enough for SICTIC PDFs versus full
  Docling tables / RTF / spreadsheets (those last two already stay local).
- Add `RUNPOD_API_KEY` to the Cloud Agent environment so later runs can use
  the API MCP to stand up endpoints instead of clicking the console.

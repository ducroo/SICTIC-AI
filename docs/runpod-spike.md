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
| `DOCUMENT_CONVERTER=docling_stack` in-process | Docling Serve Pod, or a custom Serverless wrapper around `docling-serve` |
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

## Open questions

- Pay for an always-on Docling Serve GPU pod, or wrap `docling-serve` as a
  Serverless load-balancer worker so jobs can exceed 90 seconds.
- Whether `granite-docling` on vLLM is good enough for SICTIC PDFs versus full
  Docling tables / RTF / spreadsheets (those last two already stay local).
- Add `RUNPOD_API_KEY` to the Cloud Agent environment so later runs can use
  the API MCP to stand up endpoints instead of clicking the console.

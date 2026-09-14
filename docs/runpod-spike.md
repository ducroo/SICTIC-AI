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

`scripts/runpod_docling_kpi.py` creates the Hub template `qgrb3e19va`
(`quay.io/docling-project/docling-serve-cu128`) on community cloud, converts a
one-page PDF twice, then terminates the pod. It always terminates, including on
failure. The token stays in `.env.runpod` and is gitignored.

Measured numbers land in `/opt/cursor/artifacts/runpod-docling-kpi.json` after a
live run. The template has no network volume, so terminate should drop the
container disk.

## Open questions

- Pay for an always-on Docling Serve GPU pod, or wrap `docling-serve` as a
  Serverless load-balancer worker so jobs can exceed 90 seconds.
- Whether `granite-docling` on vLLM is good enough for SICTIC PDFs versus full
  Docling tables / RTF / spreadsheets (those last two already stay local).
- Add `RUNPOD_API_KEY` to the Cloud Agent environment so later runs can use
  the API MCP to stand up endpoints instead of clicking the console.

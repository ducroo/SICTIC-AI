---
name: dataset_maintenance
description: Diagnose and maintain dataset Qdrant indexes and parsed caches.
---

# Dataset Maintenance

This administrative skill owns destructive and diagnostic operations for
dataset indexes. Business skills must not contain collection pruning,
storage-layout migration, or repair logic.

## Usage

```bash
python -m skills.dataset_maintenance diagnose
python -m skills.dataset_maintenance prune
python -m skills.dataset_maintenance prune --apply
python -m skills.dataset_maintenance delete --dataset avientus
python -m skills.dataset_maintenance rebuild-index --dataset avientus
python -m skills.dataset_maintenance rebuild-index --dataset avientus --no-sync
python -m skills.dataset_maintenance activate --dataset avientus
python -m skills.dataset_maintenance archive --dataset avientus
python -m skills.dataset_maintenance create "Example Startup"
python -m skills.dataset_maintenance delete --embeddings nomic-embed-text
python -m skills.dataset_maintenance dataset-from-insight --target-dataset all-person-profile --skill person_profile
python -m skills.dataset_maintenance dataset-from-insight --target-dataset sictic-members-investor-profile --source-datasets sictic-members --skill investor_profile
python -m skills.dataset_maintenance migrate-startup-dossiers
python -m skills.dataset_maintenance migrate-insight-manifests
python -m skills.dataset_maintenance migrate-insight-manifests --apply
```

`prune` is dry-run by default. Pass `--apply` to delete orphaned collections.
`create` initializes a startup dossier under the configured storage layout. It
creates raw and parsed startup dataset folders with `data-room`, `linkedin`,
`dealum`, `snippets`, and `post-deal` subfolders, then marks the startup active.
The startup-dossier migration is also dry-run by default and writes a JSON
manifest before any optional `--apply`.

`rebuild-index` drops a dataset's Qdrant collection and re-indexes it. Use it to
give a dataset indexed before hybrid search its BM25 vectors, since Qdrant
cannot add sparse vectors to an existing collection. Parsed Markdown is kept, so
the rebuild re-embeds but never re-parses.

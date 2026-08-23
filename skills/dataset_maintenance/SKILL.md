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

`prune` is dry-run by default. Pass `--apply` to delete orphaned dataset tenants
from the shared collection for the configured embedding model.
`create` initializes a startup dossier under the configured storage layout. It
creates raw and parsed startup dataset folders with `data-room`, `linkedin`,
`dealum`, `snippets`, and `post-deal` subfolders, then marks the startup active.
The startup-dossier migration is also dry-run by default and writes a JSON
manifest before any optional `--apply`.

`rebuild-index` deletes only the selected dataset's points from the shared
Qdrant collection for the configured embedding model and re-indexes it with
that same model. Parsed Markdown is kept, so the rebuild re-embeds but never
re-parses or affects another dataset tenant. Model overrides intentionally are
not supported by this command; change the configured embedding model first if
the target model must change.

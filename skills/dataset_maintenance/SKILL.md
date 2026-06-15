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
python -m skills.dataset_maintenance delete --embeddings nomic-embed-text
python -m skills.dataset_maintenance from-insight --insight person_profile
python -m skills.dataset_maintenance from-insight --insight investor_profile --source-dataset sictic-members
python -m skills.dataset_maintenance migrate-startup-dossiers
python -m skills.dataset_maintenance migrate-insight-manifests
python -m skills.dataset_maintenance migrate-insight-manifests --apply
```

`prune` is dry-run by default. Pass `--apply` to delete orphaned collections.
The startup-dossier migration is also dry-run by default and writes a JSON
manifest before any optional `--apply`.

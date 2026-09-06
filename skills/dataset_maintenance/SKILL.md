---
name: dataset_maintenance
description: Diagnose, reset and reconcile dataset indexes and storage layouts. Use for explicit operational maintenance, including deletion and migration.
---

# Dataset maintenance

Operate on dataset indexes and storage through the existing shared abstractions.

## Operations and effects

| CLI operation | Scope and default |
|---|---|
| `diagnose` | List present/orphaned tenants for the selected embedding model. Adapter initialization may reconcile legacy layouts. |
| `prune` | List orphaned tenants; delete them only with `--apply`. |
| `delete --dataset D` | Immediately delete D's tenant across shared model collections **and its parsed directory**. Raw sources and insights remain. |
| `delete --dataset D --embeddings M` | Immediately delete one tenant/model and reset matching index metadata; preserve parsed files. |
| `delete --embeddings M` | Immediately delete the entire shared model collection and reset affected dataset manifests. |
| `rebuild-index --dataset D` | Reset that tenant for the configured embedding model, preserving parsing checkpoints; then synchronize by default. `--no-sync` stops after reset. |
| `activate` / `archive` | Set/remove refresh eligibility markers; do not delete the dataset. |
| `create` | Create the standard startup dossier and activate it. |
| `dataset-from-insight` | Reconcile selected insights into a generated dataset; can remove obsolete target files. Writes by default; `--dry-run` previews. Does not index. |
| `migrate-startup-dossiers` | Plan layout changes and write a JSON manifest; `--apply` performs them. Conflicts produce an unsuccessful CLI exit. |
| `migrate-insight-manifests` | Preview reconstructable freshness metadata; `--apply` writes it. Skip manual/dynamic or unknown cases. |

A rebuild preserves valid parsed output, but subsequent normal synchronization
can reparse changed sources, missing output or changed parser configuration.
There is no blanket “never re-parses” guarantee.

Operations return their existing diagnostic/count/result types. Errors can leave
earlier operations completed; no cross-operation rollback is promised.
Legacy insight-manifest reconstruction contains old ranking/profile recipes;
it does not establish equivalence with every current skill cache key.

## Usage

```bash
conda run -n sictic-env python -m skills.dataset_maintenance diagnose
conda run -n sictic-env python -m skills.dataset_maintenance prune
conda run -n sictic-env python -m skills.dataset_maintenance rebuild-index --dataset example-startup --no-sync
conda run -n sictic-env python -m skills.dataset_maintenance dataset-from-insight --target-dataset example-generated --skill person_profile --dry-run
```

These operations are not harness or bulk-refresh jobs. Use command `--help`
for selectors; `delete` has no dry-run flag.

## References

- [Index operations](maintenance.py), [CLI](__main__.py)
- [Dossier migration](startup_dossiers.py), [insight metadata migration](insight_manifests.py)
- [Shared storage contracts](../standards_and_architecture/SKILL.md#datasets-and-storage)

# Documentation consistency inventory — 6 September 2026

Current status: see the [documentation closeout](documentation-closeout-2026-09-06.md). The observations and proposals below retain their historical audit context.

Snapshot: local `main` at `1be1a27`, including the approved, uncommitted AGENTS/standards reorganization. This is an audit artifact, not a new source of repository rules.

Static AST inventory; no workflow or external service was invoked to build it. Non-private definitions are candidate API surfaces, not an assertion that every helper is public. Re-exports and dynamically generated behavior require category review. See the [discrepancy register](documentation-consistency-audit-2026-09-06.md).

## Documents and exposure

| Skill | Lines | Top heading | `## Usage` | Typer module | Harness | Bulk key | Existing test classification |
|---|---:|---|---|---|---|---|---|
| [advocates](../../skills/advocates/SKILL.md) | 23 | ## Usage | Yes | Yes | /advocates | — | local-smoke |
| [bulk_refresh](../../skills/bulk_refresh/SKILL.md) | 44 | # Bulk Refresh Skill | Yes | Yes | — | — | existing-unit |
| [dataset_chat](../../skills/dataset_chat/SKILL.md) | 47 | # Dataset_Chat Skill | Yes | Yes | /dataset_chat | — | harness-smoke |
| [dataset_maintenance](../../skills/dataset_maintenance/SKILL.md) | 45 | # Dataset Maintenance | Yes | Yes | — | — | utility-smoke |
| [dd_checks](../../skills/dd_checks/SKILL.md) | 38 | # M&A Due Diligence Checklist | Yes | Yes | /dd_checks | dd-checks | local-smoke |
| [dd_priorities](../../skills/dd_priorities/SKILL.md) | 30 | # DD Priorities | Yes | Yes | /dd_priorities | dd-priorities | local-smoke |
| [dealum_import](../../skills/dealum_import/SKILL.md) | 66 | # Dealum Import | Yes | Yes | /dealum_import | — | utility-smoke |
| [deep_dive_invitation](../../skills/deep_dive_invitation/SKILL.md) | 60 | # Deep-dive invitation | No | Yes | /deep_dive_invitation | — | local-smoke |
| [expert_search](../../skills/expert_search/SKILL.md) | 16 | ## Usage | Yes | Yes | /expert_search | expert-search | local-smoke |
| [harness](../../skills/harness/SKILL.md) | 16 | ## Usage | Yes | Yes | — | — | existing-unit |
| [investor_profile](../../skills/investor_profile/SKILL.md) | 32 | # Investor Profile | Yes | Yes | /investor_profile | investor-profile | local-smoke |
| [linkedin_maintenance](../../skills/linkedin_maintenance/SKILL.md) | 16 | # LinkedIn Maintenance | No | Yes | — | — | utility-smoke |
| [llm_chat](../../skills/llm_chat/SKILL.md) | 39 | # LLM Chat Skill | Yes | Yes | — | — | utility-smoke |
| [member_preferences](../../skills/member_preferences/SKILL.md) | 27 | # Member preferences | Yes | Yes | /member_preferences | — | utility-smoke |
| [person_profile](../../skills/person_profile/SKILL.md) | 63 | ## Skill Prompt: `person_profile` | Yes | Yes | /person_profile | person-profile | local-smoke |
| [persons_in_dataset](../../skills/persons_in_dataset/SKILL.md) | 16 | # Persons in dataset | No | Yes | /persons_in_dataset | persons-in-dataset | existing-unit |
| [potential_investors](../../skills/potential_investors/SKILL.md) | 53 | ## Skill Prompt: `potential_investors` | Yes | Yes | /potential_investors | potential-investors | local-smoke |
| [ranking](../../skills/ranking/SKILL.md) | 30 | # Skill: Ranking | No | Yes | — | — | utility-smoke |
| [sha_review](../../skills/sha_review/SKILL.md) | 39 | # Shareholders' Agreement Review | Yes | Yes | /sha_review | sha-review | local-smoke |
| [standards_and_architecture](../../skills/standards_and_architecture/SKILL.md) | 517 | # Standards and Architecture | No | No | — | — | docs-only |
| [startup_profile](../../skills/startup_profile/SKILL.md) | 22 | # Startup Profile | Yes | Yes | /startup_profile | startup-profile | local-smoke |
| [startup_traction](../../skills/startup_traction/SKILL.md) | 49 | # Startup Traction & Commercial Agreements Summarizer | Yes | Yes | /startup_traction | startup-traction | local-smoke |
| [startup_website_import](../../skills/startup_website_import/SKILL.md) | 36 | # Startup Website Import | Yes | Yes | — | — | utility-smoke |
| [submission_ready](../../skills/submission_ready/SKILL.md) | 46 | # Submission Ready | Yes | Yes | /submission_ready | submission-ready | local-smoke |
| [suggested_startups](../../skills/suggested_startups/SKILL.md) | 54 | ## Skill Prompt: `suggested_startups` | Yes | Yes | /suggested_startups | suggested-startups | local-smoke |
| [team_profile](../../skills/team_profile/SKILL.md) | 40 | # Team Profiling Skill | Yes | Yes | /team_profile | team-profile | local-smoke |
| [team_profile_revised](../../skills/team_profile_revised/SKILL.md) | 22 | Absent | No | Yes | /team_profile_revised | team-profile-revised | local-smoke |

“No” is an inventory result, not necessarily a defect: instruction-only and operational skills need different templates. Harness `help`/`exit` controls are handled outside its business-command registry.

## Registry dependencies

| Key | Callable | Domains | Prerequisites |
|---|---|---|---|
| startup-profile | `startup_profile` | startups | — |
| persons-in-dataset | `persons_in_dataset` | community, startups | — |
| person-profile | `person_profile` | community, startups | persons-in-dataset |
| team-profile | `team_profile` | startups | startup-profile, person-profile |
| team-profile-revised | `team_profile_revised` | startups | startup-profile, person-profile |
| startup-traction | `startup_traction` | startups | startup-profile |
| dd-checks | `dd_checks` | startups | startup-profile |
| dd-priorities | `dd_priorities` | startups | dd-checks |
| sha-review | `sha_review` | startups | — |
| submission-ready | `submission_ready` | startups | — |
| investor-profile | `investor_profile` | community | person-profile |
| expert-search | `expert_search` | startups | startup-profile, investor-profile |
| potential-investors | `potential_investors` | startups | startup-profile, investor-profile |
| suggested-startups | `suggested_startups` | community | startup-profile, investor-profile |

## Harness command inventory

| Command | Declared usage |
|---|---|
| `/config` | `/config` |
| `/sync` | `/sync <dataset>` |
| `/dataset_chat` | `/dataset_chat <dataset> <question>` |
| `/startup_profile` | `/startup_profile <startup>` |
| `/startup_traction` | `/startup_traction <startup>` |
| `/persons_in_dataset` | `/persons_in_dataset <dataset>` |
| `/person_profile` | `/person_profile <dataset> <person>` |
| `/team_profile` | `/team_profile <startup>` |
| `/team_profile_revised` | `/team_profile_revised <startup>` |
| `/investor_profile` | `/investor_profile [--source-dataset dataset]` |
| `/expert_search` | `/expert_search <startup>` |
| `/potential_investors` | `/potential_investors <startup>` |
| `/member_preferences` | `/member_preferences [--dataset sictic-members]` |
| `/deep_dive_invitation` | `/deep_dive_invitation --startup name [--founders contacts] [--investors contacts]` |
| `/advocates` | `/advocates <event> --description "..."` |
| `/suggested_startups` | `/suggested_startups --startups a,b --investor x,y` |
| `/submission_ready` | `/submission_ready [startup ...]` |
| `/dd_checks` | `/dd_checks <startup>` |
| `/dd_priorities` | `/dd_priorities <startup>` |
| `/sha_review` | `/sha_review <dataset>` |
| `/dealum_import` | `/dealum_import <startup>` |

## Skill definition inventory

Signatures are extracted from non-CLI module-level functions. `InsightResult` is the existing alias for `list[InsightFile]`; do not rename signatures solely to normalize their spelling.

### advocates

- [skills/advocates/advocates.py](../../skills/advocates/advocates.py) line 15: `async advocates(event_name: str, event_description: str, target_members: Optional[List[str]]=None, exclude_members: Optional[List[str]]=None, top_k: int=10) -> InsightResult`

### bulk_refresh

- [skills/bulk_refresh/bulk_refresh.py](../../skills/bulk_refresh/bulk_refresh.py) line 230: `async bulk_refresh(datasets: str | None=None, skills: str | None=None) -> None`

### dataset_chat

- [skills/dataset_chat/dataset_chat.py](../../skills/dataset_chat/dataset_chat.py) line 41: `async dataset_chat(dataset_name: str, queries: str | list[str], prompt: str, max_chunks: int=25, strict_insufficient_context: bool=True, cacheable_prompt_prefix: str | None=None) -> str | None`
- [skills/dataset_chat/dataset_chat.py](../../skills/dataset_chat/dataset_chat.py) line 67: `async dataset_chat_json(dataset_name: str, queries: str | list[str], prompt: str, schema: dict[str, Any], reviewer: Callable[[dict | list], Review[dict | list]] | None=None, *, max_chunks: int=25, cacheable_prompt_prefix: str | None=None, allow_empty_retrieval: bool=False) -> dict | list | None`

### dataset_maintenance

- [skills/dataset_maintenance/insight_manifests.py](../../skills/dataset_maintenance/insight_manifests.py) line 156: `migrate_insight_manifests(*, apply: bool=False) -> InsightMigrationResult`
- [skills/dataset_maintenance/maintenance.py](../../skills/dataset_maintenance/maintenance.py) line 78: `orphaned_qdrant_collections(embeddings: Optional[str]=None, *, adapter: QdrantAdapter | None=None) -> list[str]`
- [skills/dataset_maintenance/maintenance.py](../../skills/dataset_maintenance/maintenance.py) line 96: `diagnose_qdrant_collections(embeddings: Optional[str]=None, *, adapter: QdrantAdapter | None=None) -> list[CollectionDiagnostic]`
- [skills/dataset_maintenance/maintenance.py](../../skills/dataset_maintenance/maintenance.py) line 117: `prune_orphaned_qdrant_collections(embeddings: Optional[str]=None, *, apply: bool=False, adapter: QdrantAdapter | None=None) -> list[str]`
- [skills/dataset_maintenance/maintenance.py](../../skills/dataset_maintenance/maintenance.py) line 139: `delete_dataset_index(dataset: Optional[str]=None, embeddings: Optional[str]=None) -> list[str]`
- [skills/dataset_maintenance/maintenance.py](../../skills/dataset_maintenance/maintenance.py) line 199: `rebuild_dataset_index(dataset: str) -> IndexRebuild`
- [skills/dataset_maintenance/maintenance.py](../../skills/dataset_maintenance/maintenance.py) line 227: `activate_dataset_marker(dataset: str) -> str`
- [skills/dataset_maintenance/maintenance.py](../../skills/dataset_maintenance/maintenance.py) line 234: `archive_dataset_marker(dataset: str) -> str`
- [skills/dataset_maintenance/startup_dossiers.py](../../skills/dataset_maintenance/startup_dossiers.py) line 140: `build_plan(mirror_root: Path) -> dict`
- [skills/dataset_maintenance/startup_dossiers.py](../../skills/dataset_maintenance/startup_dossiers.py) line 166: `apply_plan(plan: dict) -> None`
- [skills/dataset_maintenance/startup_dossiers.py](../../skills/dataset_maintenance/startup_dossiers.py) line 213: `migrate_startup_dossiers(*, apply: bool=False, manifest_path: str='startup-dossier-migration.json') -> dict`

### dd_checks

- [skills/dd_checks/dd_checks.py](../../skills/dd_checks/dd_checks.py) line 50: `parse_industry_type(response: str, allowed_industry_types: set[str], response_schema: dict[str, Any]) -> str`
- [skills/dd_checks/dd_checks.py](../../skills/dd_checks/dd_checks.py) line 104: `async find_industry_type(startup_name_lower: str, dd_config: dict, allowed_industry_types: set) -> str`
- [skills/dd_checks/dd_checks.py](../../skills/dd_checks/dd_checks.py) line 139: `async chapter_by_chapter(startup_name_lower: str, sorted_chapters: list, industry_type: str, dd_config: dict, batch_instructions: str) -> list[str]`
- [skills/dd_checks/dd_checks.py](../../skills/dd_checks/dd_checks.py) line 215: `async dd_checks(startup: str) -> InsightResult`

### dd_priorities

- [skills/dd_priorities/dd_priorities.py](../../skills/dd_priorities/dd_priorities.py) line 28: `async dd_priorities(startup: str) -> InsightResult`

### dealum_import

- [skills/dealum_import/dealum_import.py](../../skills/dealum_import/dealum_import.py) line 6: `async dealum_import(startup: str) -> DealumImportResult`

### deep_dive_invitation

- [skills/deep_dive_invitation/deep_dive_invitation.py](../../skills/deep_dive_invitation/deep_dive_invitation.py) line 43: `parse_people_csv(value: str | None) -> list[Person]`
- [skills/deep_dive_invitation/deep_dive_invitation.py](../../skills/deep_dive_invitation/deep_dive_invitation.py) line 366: `async deep_dive_invitation(startup: str, founders: list[Person] | None=None, investors: list[Person] | None=None) -> InsightResult`

### expert_search

- [skills/expert_search/expert_search.py](../../skills/expert_search/expert_search.py) line 16: `async expert_search(startup_name: str, target_experts: Optional[List[str]]=None, exclude_experts: Optional[List[str]]=None, top_k: int=16) -> InsightResult`

### harness

- [skills/harness/harness.py](../../skills/harness/harness.py) line 288: `build_registry() -> Dict[str, HarnessCommand]`
- [skills/harness/harness.py](../../skills/harness/harness.py) line 330: `help_text(registry: Dict[str, HarnessCommand] | None=None) -> str`
- [skills/harness/harness.py](../../skills/harness/harness.py) line 340: `async dispatch_command(line: str, registry: Dict[str, HarnessCommand] | None=None) -> str`
- [skills/harness/harness.py](../../skills/harness/harness.py) line 379: `async run_repl() -> None`
- [skills/harness/harness.py](../../skills/harness/harness.py) line 400: `run() -> None`

### investor_profile

- [skills/investor_profile/investor_profile.py](../../skills/investor_profile/investor_profile.py) line 154: `async investor_profile(source_dataset: str='sictic-members', names: list[str] | None=None) -> InsightResult`
- [skills/investor_profile/investor_profile.py](../../skills/investor_profile/investor_profile.py) line 163: `read_investor_profiles(source_dataset: str, names: List[str]) -> dict[str, str]`

### linkedin_maintenance

- [skills/linkedin_maintenance/maintenance.py](../../skills/linkedin_maintenance/maintenance.py) line 22: `missing_profile_urls(entries: list[dict]) -> list[str]`
- [skills/linkedin_maintenance/maintenance.py](../../skills/linkedin_maintenance/maintenance.py) line 33: `missing_profiles() -> list[dict]`

### llm_chat

No non-private module-level function outside the CLI. Inspect package/CLI and skill type before proposing a facade.

### member_preferences

- [skills/member_preferences/member_preferences.py](../../skills/member_preferences/member_preferences.py) line 19: `preferences_for(person: Person) -> dict[str, object]`
- [skills/member_preferences/member_preferences.py](../../skills/member_preferences/member_preferences.py) line 24: `member_preferences(dataset_name: str='sictic-members') -> list[Person]`
- [skills/member_preferences/member_preferences.py](../../skills/member_preferences/member_preferences.py) line 40: `render_member_preferences(people: list[Person]) -> str`

### person_profile

- [skills/person_profile/person_profile.py](../../skills/person_profile/person_profile.py) line 160: `async person_profile(dataset_name: str, names: str | list[str]=None, *, include_dataset_context: bool=True) -> InsightResult`
- [skills/person_profile/person_profile.py](../../skills/person_profile/person_profile.py) line 175: `async person_profile_as_person_objects(dataset_name: str, names: str | list[str]=None, *, include_dataset_context: bool=True) -> list[Person]`

### persons_in_dataset

- [skills/persons_in_dataset/persons_in_dataset.py](../../skills/persons_in_dataset/persons_in_dataset.py) line 88: `async persons_in_dataset_as_person_objects(dataset_name: str) -> list[Person]`
- [skills/persons_in_dataset/persons_in_dataset.py](../../skills/persons_in_dataset/persons_in_dataset.py) line 135: `async persons_in_dataset(dataset_name: str) -> InsightResult`

### potential_investors

- [skills/potential_investors/potential_investors.py](../../skills/potential_investors/potential_investors.py) line 16: `async potential_investors(startup_name: str, target_investors: Optional[List[str]]=None, exclude_investors: Optional[List[str]]=None, top_k: int=16) -> InsightResult`

### ranking

- [skills/ranking/ranking_persons.py](../../skills/ranking/ranking_persons.py) line 92: `render_person_ranking(rows: List[dict[str, Any]]) -> str`
- [skills/ranking/ranking_persons.py](../../skills/ranking/ranking_persons.py) line 110: `async rank_person_rows(source_datasets: Optional[List[str]]=None, skill: str='investor_profile', objective: str='', candidates: Optional[List[str]]=None, optout: Optional[List[str]]=None, top_k: int=8, member_dataset: str='sictic-members') -> List[dict[str, Any]]`
- [skills/ranking/ranking_persons.py](../../skills/ranking/ranking_persons.py) line 219: `async ranking_persons(source_datasets: Optional[List[str]]=None, skill: str='investor_profile', objective: str='', candidates: Optional[List[str]]=None, optout: Optional[List[str]]=None, top_k: int=8, member_dataset: str='sictic-members') -> str`
- [skills/ranking/ranking_rationale.py](../../skills/ranking/ranking_rationale.py) line 60: `async ranking_rationale(ranked_items: List[Dict[str, Any]], objective: str) -> List[Dict[str, Any]]`
- [skills/ranking/ranking_top_k.py](../../skills/ranking/ranking_top_k.py) line 103: `async rank_chunk(objective: str, profiles: Dict[str, str]) -> List[str]`
- [skills/ranking/ranking_top_k.py](../../skills/ranking/ranking_top_k.py) line 157: `async ranking_top_k(objective: str, all_profiles: Dict[str, str], top_k: int=8, batch_size: int=DEFAULT_BATCH_SIZE) -> Tuple[List[Dict[str, Any]], int]`

### sha_review

- [skills/sha_review/sha_review.py](../../skills/sha_review/sha_review.py) line 378: `async sha_review(dataset_name: str) -> InsightResult`

### standards_and_architecture

No non-private module-level function outside the CLI. Inspect package/CLI and skill type before proposing a facade.

### startup_profile

- [skills/startup_profile/startup_profile.py](../../skills/startup_profile/startup_profile.py) line 16: `async startup_profile(startup: str, files: Optional[List[str]]=None) -> InsightResult`

### startup_traction

- [skills/startup_traction/startup_traction.py](../../skills/startup_traction/startup_traction.py) line 11: `async startup_traction(startup_name: str) -> InsightResult`

### startup_website_import

- [skills/startup_website_import/startup_website_import.py](../../skills/startup_website_import/startup_website_import.py) line 155: `startup_website_import(startup_name: str, url: str, *, depth: int=1, max_pages: int=50, include_pdfs: bool=True, max_pdfs: int=20, max_pdf_mb: int=25, respect_robots: bool=True, session: requests.Session | None=None, storage: Storage | None=None) -> WebsiteImportResult`

### submission_ready

- [skills/submission_ready/submission_ready.py](../../skills/submission_ready/submission_ready.py) line 656: `async submission_ready(startups: str | list[str] | None=None) -> InsightResult`

### suggested_startups

- [skills/suggested_startups/generation.py](../../skills/suggested_startups/generation.py) line 23: `compile_startup_profiles(profiles: list[InsightFile]) -> dict[str, str]`
- [skills/suggested_startups/generation.py](../../skills/suggested_startups/generation.py) line 38: `async generate_report(investor: str, investor_profile: str, startup_profiles: dict[str, str], objective_template: str, max_startups: int) -> str`
- [skills/suggested_startups/generation.py](../../skills/suggested_startups/generation.py) line 74: `render_report(investor: str, suggestions: list[Suggestion]) -> str`
- [skills/suggested_startups/inputs.py](../../skills/suggested_startups/inputs.py) line 34: `load_skill_config(config: dict) -> SuggestedStartupsConfig`
- [skills/suggested_startups/inputs.py](../../skills/suggested_startups/inputs.py) line 60: `resolve_request(dataset_name: str, startups: list[str] | None, investors: list[str] | None, max_startups: int, *, config: dict, available_startups: list[str]) -> SuggestedStartupsRequest`
- [skills/suggested_startups/inputs.py](../../skills/suggested_startups/inputs.py) line 166: `async load_startup_profiles(startups: list[str]) -> list[InsightFile]`
- [skills/suggested_startups/inputs.py](../../skills/suggested_startups/inputs.py) line 186: `load_investor_profiles(dataset: str, investors: list[Person]) -> dict[str, str]`
- [skills/suggested_startups/suggested_startups.py](../../skills/suggested_startups/suggested_startups.py) line 58: `async suggested_startups(dataset_name: str='sictic_members', startups: Optional[List[str]]=None, investors: Optional[List[str]]=None, max_startups: int=5) -> InsightResult`

### team_profile

- [skills/team_profile/team_profile.py](../../skills/team_profile/team_profile.py) line 13: `async team_profile(startup_name: str) -> InsightResult`

### team_profile_revised

- [skills/team_profile_revised/team_profile_revised.py](../../skills/team_profile_revised/team_profile_revised.py) line 96: `async team_profile_revised(startup_name: str) -> InsightResult`

## Library definition inventory

Every library Python module is listed below. Names include non-private module-level functions, classes and their non-private methods/properties; private methods and constructors are omitted. This is an inventory, not a claim-by-claim behavioral sign-off.

| Module | Candidate API definitions |
|---|---|
| [lib/__init__.py](../../lib/__init__.py) | Package exports/private implementation; inspect file |
| [lib/batch_audit/__init__.py](../../lib/batch_audit/__init__.py) | Package exports/private implementation; inspect file |
| [lib/batch_audit/checklist.py](../../lib/batch_audit/checklist.py) | `ChecklistCheck:8`; `ChecklistChapter:16`; `Checklist:23`; `parse_checklist:47` |
| [lib/batch_audit/engine.py](../../lib/batch_audit/engine.py) | `batch_audit:181` |
| [lib/batch_audit/rendering.py](../../lib/batch_audit/rendering.py) | `json_to_markdown_table:18` |
| [lib/batch_audit/schema.py](../../lib/batch_audit/schema.py) | `validate_audit_document:18`; `audit_errors:62` |
| [lib/cli.py](../../lib/cli.py) | `format_insights:15`; `run_command:23` |
| [lib/datasets/__init__.py](../../lib/datasets/__init__.py) | Package exports/private implementation; inspect file |
| [lib/datasets/chunking.py](../../lib/datasets/chunking.py) | `split_markdown:40`; `split_section:55`; `split_spreadsheet:85`; `chunks_for_table:107`; `table_prefix:132`; `truncate_row:145`; `pack_rows:151`; `fit_row:169`; `build_chunk:175` |
| [lib/datasets/conversion.py](../../lib/datasets/conversion.py) | `spreadsheet_cache_is_current:38`; `ignored_parse_is_current:58`; `reconcile_conversions:112` |
| [lib/datasets/documents.py](../../lib/datasets/documents.py) | `resolve_document_path:70` |
| [lib/datasets/embeddings.py](../../lib/datasets/embeddings.py) | `EmbeddingService:52`; `EmbeddingService.vector_size:57`; `EmbeddingService.embed:79`; `EmbeddingService.embed_many:87` |
| [lib/datasets/indexing.py](../../lib/datasets/indexing.py) | `reconcile_index:32`; `replace_document:279` |
| [lib/datasets/ingestion.py](../../lib/datasets/ingestion.py) | `sync_datasets:28` |
| [lib/datasets/manifest.py](../../lib/datasets/manifest.py) | `content_hash:22`; `ignored_parse_is_current:28`; `IngestionManifest:43`; `IngestionManifest.path:50`; `IngestionManifest.load:54`; `IngestionManifest.save:79`; `IngestionManifest.state:94`; `IngestionManifest.remove:97`; `IngestionManifest.update_indexed_dataset_revision:100` |
| [lib/datasets/models.py](../../lib/datasets/models.py) | `IngestionFailure:12`; `IngestionResult:19`; `IngestionResult.ok:29`; `Chunk:33`; `Chunk.to_md:41` |
| [lib/datasets/page_markers.py](../../lib/datasets/page_markers.py) | `format_page_marker:11`; `split_text_by_pages:15` |
| [lib/datasets/paths.py](../../lib/datasets/paths.py) | `DatasetLocation:17`; `DatasetLocation.raw_rel:30`; `DatasetLocation.parsed_rel:34`; `DatasetLocation.insights_rel:38`; `DatasetLocation.active_marker_rel:42`; `storage_domain_config:51`; `dataset_location_for_domain:80`; `find_dataset_location:99`; `dataset_location:116`; `dataset_raw_path:129`; `dataset_parsed_path:133`; `dataset_insights_path:137`; `dataset_active_marker_path:141`; `list_dataset_names:145`; `list_all_dataset_names:160`; `iter_domains:174` |
| [lib/datasets/reranking.py](../../lib/datasets/reranking.py) | `reranking_enabled:55`; `rerank_chunks:166` |
| [lib/datasets/retrieval.py](../../lib/datasets/retrieval.py) | `candidate_limit:29`; `max_chunks_per_document:38`; `apply_document_diversity:49` |
| [lib/datasets/search.py](../../lib/datasets/search.py) | `dataset_search:63` |
| [lib/datasets/source.py](../../lib/datasets/source.py) | `SourceDocument:52`; `list_source_files:58`; `snapshot_source_files:68`; `parsed_filepath:80` |
| [lib/datasets/sparse.py](../../lib/datasets/sparse.py) | `SparseVectorData:46`; `tokenize:56`; `token_id:68`; `encode_document:84`; `encode_query:101` |
| [lib/datasets/spreadsheet_markdown.py](../../lib/datasets/spreadsheet_markdown.py) | `SheetSection:24`; `is_spreadsheet_markdown:32`; `is_spreadsheet_filename:36`; `split_sheets:40` |
| [lib/datasets/state.py](../../lib/datasets/state.py) | `dataset_archived_marker_path:28`; `is_active_dataset:51`; `activate_dataset:56`; `archive_dataset:62` |
| [lib/ephemeral_dataset.py](../../lib/ephemeral_dataset.py) | `prepare_ephemeral_dataset:12` |
| [lib/infrastructure/__init__.py](../../lib/infrastructure/__init__.py) | Package exports/private implementation; inspect file |
| [lib/infrastructure/ai_text_generation/__init__.py](../../lib/infrastructure/ai_text_generation/__init__.py) | Package exports/private implementation; inspect file |
| [lib/infrastructure/ai_text_generation/generation.py](../../lib/infrastructure/ai_text_generation/generation.py) | `generate_markdown:81`; `generate_json:132` |
| [lib/infrastructure/ai_text_generation/json.py](../../lib/infrastructure/ai_text_generation/json.py) | `copy_schema:28`; `add_temporary_reasoning_field:33`; `remove_temporary_reasoning:78`; `schema_text:98`; `schema_prompt_block:102`; `json_schema_response_format:117`; `validate_schema:136`; `validate_json_schema:144`; `parse_json_response:162`; `repair_json_payload:173` |
| [lib/infrastructure/ai_text_generation/measurements.py](../../lib/infrastructure/ai_text_generation/measurements.py) | `measurements_enabled:28`; `active_local_jobs:33`; `record_attempt:46` |
| [lib/infrastructure/ai_text_generation/types.py](../../lib/infrastructure/ai_text_generation/types.py) | `Review:13`; `Review.accepted:20` |
| [lib/infrastructure/apify.py](../../lib/infrastructure/apify.py) | `ApifyAdapter:13`; `ApifyAdapter.run_actor:18`; `ApifyAdapter.start_actor:36`; `ApifyAdapter.wait_for_run:47`; `ApifyAdapter.get_run:56`; `ApifyAdapter.run_items:62`; `ApifyAdapter.delete_run:71` |
| [lib/infrastructure/configuration.py](../../lib/infrastructure/configuration.py) | `get_env_var:27`; `get_env_var:31`; `get_env_var:34`; `config_cache_key:51`; `load_repository_config:197` |
| [lib/infrastructure/dealum.py](../../lib/infrastructure/dealum.py) | `DealumFileLink:20`; `DealumAdapter:26`; `DealumAdapter.is_configured:42`; `DealumAdapter.list_applications:50`; `DealumAdapter.extract_file_links:67`; `DealumAdapter.file_metadata:86`; `DealumAdapter.download_file:97`; `safe_filename_from_url:114` |
| [lib/infrastructure/document_conversion/__init__.py](../../lib/infrastructure/document_conversion/__init__.py) | Package exports/private implementation; inspect file |
| [lib/infrastructure/document_conversion/converter.py](../../lib/infrastructure/document_conversion/converter.py) | `convert_document:24` |
| [lib/infrastructure/document_conversion/docling_stack/__init__.py](../../lib/infrastructure/document_conversion/docling_stack/__init__.py) | Package exports/private implementation; inspect file |
| [lib/infrastructure/document_conversion/docling_stack/converter.py](../../lib/infrastructure/document_conversion/docling_stack/converter.py) | `convert_document:40` |
| [lib/infrastructure/document_conversion/docling_stack/docling.py](../../lib/infrastructure/document_conversion/docling_stack/docling.py) | `build_converter:19`; `get_converter:76`; `get_force_ocr_converter:90`; `export_document_markdown:103`; `convert_document:128`; `convert_document_force_ocr:135`; `picture_description_params:142`; `chat_completions_url:151`; `chat_completions_model:158` |
| [lib/infrastructure/document_conversion/docling_stack/pdf.py](../../lib/infrastructure/document_conversion/docling_stack/pdf.py) | `repair_pdf:11`; `repaired_pdf:44`; `convert_repaired_pdf:56` |
| [lib/infrastructure/document_conversion/docling_stack/rtf.py](../../lib/infrastructure/document_conversion/docling_stack/rtf.py) | `convert_rtf:1` |
| [lib/infrastructure/document_conversion/docling_stack/spreadsheets.py](../../lib/infrastructure/document_conversion/docling_stack/spreadsheets.py) | `is_spreadsheet_filename:22`; `convert_spreadsheet:26`; `convert_openpyxl:34`; `convert_xls:132`; `escape_markdown_cell:170`; `render_rows:174`; `pad_row:199`; `render_prose_row:203`; `render_row:208`; `render_separator:216`; `format_cell_value:220`; `format_temporal:235`; `format_float:245`; `format_magnitude:253`; `render_spreadsheet_markdown:267`; `xls_cell_text:274` |
| [lib/infrastructure/document_conversion/normalization.py](../../lib/infrastructure/document_conversion/normalization.py) | `has_dense_private_use_encoding:12`; `requires_text_normalization:20`; `normalize_extracted_text:29` |
| [lib/infrastructure/document_conversion/types.py](../../lib/infrastructure/document_conversion/types.py) | `DocumentConversion:9` |
| [lib/infrastructure/errors.py](../../lib/infrastructure/errors.py) | `InfrastructureErrorKind:9`; `InfrastructureError:36` |
| [lib/infrastructure/logging.py](../../lib/infrastructure/logging.py) | `get_logger:94` |
| [lib/infrastructure/qdrant.py](../../lib/infrastructure/qdrant.py) | `QdrantAdmin:57`; `QdrantAdmin.list_collections:66`; `QdrantAdmin.delete_collection:72`; `QdrantAdapter:76`; `QdrantAdapter.collection_for:80`; `QdrantAdapter.legacy_collection_for:89`; `QdrantAdapter.list_collections:256`; `QdrantAdapter.collection_exists:262`; `QdrantAdapter.ensure_collection:265`; `QdrantAdapter.sparse_enabled:303`; `QdrantAdapter.collection_info:312`; `QdrantAdapter.collection_vector_size:323`; `QdrantAdapter.collection_points_count:331`; `QdrantAdapter.list_indexed_datasets:341`; `QdrantAdapter.get_document_mtimes:356`; `QdrantAdapter.get_document_point_ids:389`; `QdrantAdapter.delete_point_ids:417`; `QdrantAdapter.delete_document:431`; `QdrantAdapter.upsert_points:474`; `QdrantAdapter.query:515`; `QdrantAdapter.query_hybrid:537`; `QdrantAdapter.delete_dataset:586` |
| [lib/infrastructure/retry.py](../../lib/infrastructure/retry.py) | `with_rate_limit_retry:26` |
| [lib/infrastructure/scheduler.py](../../lib/infrastructure/scheduler.py) | `SchedulingTimeoutError:71`; `SchedulerLease:85`; `SchedulerRequest:102`; `default_scheduler_state_path:118`; `Scheduler:155`; `Scheduler.snapshot:431`; `Scheduler.run:455`; `Scheduler.slot:522` |
| [lib/infrastructure/scheduler_operations.py](../../lib/infrastructure/scheduler_operations.py) | `JobProfile:12`; `register_operation:28`; `inspect_operation:41` |
| [lib/infrastructure/scheduler_policy.py](../../lib/infrastructure/scheduler_policy.py) | `SchedulerPolicy:12`; `SchedulerPolicy.counts:27`; `SchedulerPolicy.descriptor:44`; `SchedulerPolicy.is_constrained_local_descriptor:53`; `SchedulerPolicy.active_local_descriptors:61`; `SchedulerPolicy.descriptor_lease_count:72`; `SchedulerPolicy.pending_requests:80`; `SchedulerPolicy.matches_affinity:89`; `SchedulerPolicy.is_admissible:95`; `SchedulerPolicy.grant_available:112`; `SchedulerPolicy.remove_request:194`; `SchedulerPolicy.release:206`; `SchedulerPolicy.heartbeat:240` |
| [lib/infrastructure/scheduler_state.py](../../lib/infrastructure/scheduler_state.py) | `SchedulerStateStore:23`; `SchedulerStateStore.locked:31`; `SchedulerStateStore.read:40`; `SchedulerStateStore.read_clean:52`; `SchedulerStateStore.write:204` |
| [lib/infrastructure/web_search.py](../../lib/infrastructure/web_search.py) | `WebSearchResult:13`; `WebSearchAdapter:21`; `WebSearchAdapter.search:25` |
| [lib/insights/__init__.py](../../lib/insights/__init__.py) | Package exports/private implementation; inspect file |
| [lib/insights/context.py](../../lib/insights/context.py) | Package exports/private implementation; inspect file |
| [lib/insights/discovery.py](../../lib/insights/discovery.py) | `InsightCandidate:14`; `discover_insights:26` |
| [lib/insights/file.py](../../lib/insights/file.py) | `InsightFile:34`; `InsightFile.directory:66`; `InsightFile.filename:77`; `InsightFile.path:90`; `InsightFile.dataset_relative_path:94`; `InsightFile.exists:117`; `InsightFile.content:120`; `InsightFile.has_insufficient_context:123`; `InsightFile.find:127`; `InsightFile.find_all:131`; `InsightFile.is_reusable:230`; `InsightFile.save:233` |
| [lib/insights/hydration.py](../../lib/insights/hydration.py) | `select_insights:17`; `dataset_from_insight:30` |
| [lib/insights/locking.py](../../lib/insights/locking.py) | `atomic_write:14`; `write_if_changed:35`; `manifest_write_lock:47` |
| [lib/insights/manifest.py](../../lib/insights/manifest.py) | `config_hash:19`; `dataset_revisions:23`; `load_insight_manifest:37`; `save_insight_entry:57` |
| [lib/insights/naming.py](../../lib/insights/naming.py) | `strip_model_tag:7`; `insight_model_slug:32` |
| [lib/insights/paths.py](../../lib/insights/paths.py) | `model_slug:10`; `insight_directory:14`; `insight_filename:32`; `insight_base:48`; `insight_manifest_path:59` |
| [lib/insights/selection.py](../../lib/insights/selection.py) | `ranked_models:21`; `find:29`; `is_reusable:65`; `fallback_sort_key:110` |
| [lib/linkedin_ids.py](../../lib/linkedin_ids.py) | `normalize_linkedin_id:6` |
| [lib/litellm_cleanup.py](../../lib/litellm_cleanup.py) | `close_litellm_sessions:4` |
| [lib/markdown_tables.py](../../lib/markdown_tables.py) | `TableBlock:27`; `is_table_line:35`; `split_cells:39`; `is_separator_row:46`; `looks_numeric:53`; `label_count:67`; `header_score:73`; `select_header:87`; `parse_table:114`; `iter_segments:141` |
| [lib/model_config.py](../../lib/model_config.py) | `ModelEndpoint:10`; `ModelEndpoint.litellm_kwargs:15`; `llm_endpoint:44`; `embedding_endpoint:54`; `rerank_endpoint:64`; `llm_model:76`; `embedding_model:80` |
| [lib/people/__init__.py](../../lib/people/__init__.py) | Package exports/private implementation; inspect file |
| [lib/people/discovery.py](../../lib/people/discovery.py) | `manual_persons_in_dataset:114`; `persons_in_dataset:129` |
| [lib/people/dossier.py](../../lib/people/dossier.py) | `person_in_filename:36`; `is_personal_document:58`; `get_filtered_chunks:64`; `build_person_dossier:90` |
| [lib/people/linkedin/__init__.py](../../lib/people/linkedin/__init__.py) | Package exports/private implementation; inspect file |
| [lib/people/linkedin/cleaning.py](../../lib/people/linkedin/cleaning.py) | `clean_linkedin_payload:16` |
| [lib/people/linkedin/identity.py](../../lib/people/linkedin/identity.py) | `extract_linkedin_id:11`; `linkedin_profile_not_found:24` |
| [lib/people/linkedin/maintenance.py](../../lib/people/linkedin/maintenance.py) | `diagnose_registry:25`; `import_profiles:52` |
| [lib/people/linkedin/registry.py](../../lib/people/linkedin/registry.py) | `default_registry_path:29`; `LinkedInRegistry:33`; `LinkedInRegistry.load:73`; `LinkedInRegistry.save:86`; `LinkedInRegistry.update:116`; `LinkedInRegistry.find:148`; `LinkedInRegistry.upsert:156`; `LinkedInRegistry.set_status:189`; `LinkedInRegistry.remove_identity:203`; `LinkedInRegistry.mark_status:215` |
| [lib/people/linkedin/service.py](../../lib/people/linkedin/service.py) | `sanitize_name:35`; `find_cached_person:46`; `LinkedInResolver:110`; `LinkedInResolver.get_cached_persons:134`; `LinkedInResolver.get_all_persons:140`; `LinkedInResolver.get_profiles:340` |
| [lib/people/linkedin/store.py](../../lib/people/linkedin/store.py) | `LinkedInProfileStore:14`; `LinkedInProfileStore.load_all:19`; `LinkedInProfileStore.write:45` |
| [lib/people/markdown.py](../../lib/people/markdown.py) | `markdown_table_to_person_objects:63` |
| [lib/people/model.py](../../lib/people/model.py) | `normalize_email_addresses:14`; `extract_email_addresses:36`; `Person:66`; `Person.identifier:85`; `Person.display_name:94`; `Person.match_score:102`; `Person.matches:131`; `Person.find_best_match:135`; `Person.merge:151` |
| [lib/runtime_noise.py](../../lib/runtime_noise.py) | `configure_runtime_noise:14`; `suppress_native_stderr:29` |
| [lib/slugify.py](../../lib/slugify.py) | `slugify:5` |
| [lib/startups/__init__.py](../../lib/startups/__init__.py) | Package exports/private implementation; inspect file |
| [lib/startups/dealum/__init__.py](../../lib/startups/dealum/__init__.py) | Package exports/private implementation; inspect file |
| [lib/startups/dealum/importing.py](../../lib/startups/dealum/importing.py) | `DealumImportResult:40`; `import_startup_from_dealum:78` |
| [lib/startups/dealum/manifest.py](../../lib/startups/dealum/manifest.py) | `dealum_dataset_rel:19`; `dealum_manifest_path:24`; `read_manifest:28`; `dealum_url_for_startup:53`; `application_content_for_hash:61`; `replace_attachment_urls:79`; `stable_json:102`; `stable_hash:106`; `manifest_without_last_sync:110` |
| [lib/startups/dealum/matching.py](../../lib/startups/dealum/matching.py) | `DealumMatch:31`; `DealumReconciliationError:45`; `DealumApplicationNotFoundError:49`; `DealumApplicationAmbiguousError:53`; `dealum_application_url:57`; `reconcile_dealum_startup:69` |
| [lib/startups/dealum/rendering.py](../../lib/startups/dealum/rendering.py) | `render_application_markdown:9` |
| [lib/startups/dossier.py](../../lib/startups/dossier.py) | `ensure_startup_dossier:22` |
| [lib/startups/identity.py](../../lib/startups/identity.py) | `startup_aliases:12`; `canonical_startup_slug:22` |
| [lib/startups/sources.py](../../lib/startups/sources.py) | `StartupDataStatus:25`; `ensure_startup_dataset:36` |
| [lib/storage.py](../../lib/storage.py) | `Storage:19`; `Storage.read_text:20`; `Storage.write_text:21`; `Storage.read_bytes:22`; `Storage.write_bytes:23`; `Storage.exists:24`; `Storage.is_dir:25`; `Storage.list:26`; `Storage.list_with_mtime:27`; `Storage.mtime:30`; `Storage.set_mtime:31`; `Storage.remove:32`; `Storage.rmtree:33`; `Storage.mkdir:34`; `Storage.refresh:35`; `LocalStorage:51`; `LocalStorage.read_text:61`; `LocalStorage.write_text:64`; `LocalStorage.read_bytes:69`; `LocalStorage.write_bytes:72`; `LocalStorage.exists:77`; `LocalStorage.is_dir:80`; `LocalStorage.list:83`; `LocalStorage.list_with_mtime:92`; `LocalStorage.mtime:109`; `LocalStorage.set_mtime:116`; `LocalStorage.remove:120`; `LocalStorage.rmtree:126`; `LocalStorage.mkdir:131`; `LocalStorage.refresh:134`; `LocalStorage.local_path:141`; `RoutedStorage:152`; `RoutedStorage.read_text:166`; `RoutedStorage.write_text:170`; `RoutedStorage.read_bytes:174`; `RoutedStorage.write_bytes:178`; `RoutedStorage.exists:182`; `RoutedStorage.is_dir:186`; `RoutedStorage.list:190`; `RoutedStorage.list_with_mtime:194`; `RoutedStorage.mtime:200`; `RoutedStorage.set_mtime:204`; `RoutedStorage.remove:208`; `RoutedStorage.rmtree:212`; `RoutedStorage.mkdir:216`; `RoutedStorage.refresh:220`; `RoutedStorage.local_path:229`; `get_storage:240`; `reset_storage_singleton:277` |

## Instruction references

| Document | Lines | Review scope |
|---|---:|---|
| [AGENTS.md](../../AGENTS.md) | 61 | Current instructions/reference |
| [skills/standards_and_architecture/references/architecture.md](../../skills/standards_and_architecture/references/architecture.md) | 114 | Current instructions/reference |
| [skills/team_profile_revised/references/additional_team_questions.md](../../skills/team_profile_revised/references/additional_team_questions.md) | 368 | Historical source register: inventory only; not governing instructions |
| [skills/team_profile_revised/references/checklist_decisions.md](../../skills/team_profile_revised/references/checklist_decisions.md) | 95 | Current instructions/reference |
| [skills/team_profile_revised/references/original_team_questions.md](../../skills/team_profile_revised/references/original_team_questions.md) | 60 | Historical source register: inventory only; not governing instructions |
| [skills/team_profile_revised/references/team_question_hierarchy.md](../../skills/team_profile_revised/references/team_question_hierarchy.md) | 46 | Historical source register: inventory only; not governing instructions |

## Direct CLI command inventory

Declared Typer commands, argument/option names and defaults, extracted without running the commands. Defaults shown as code are CLI parser declarations, not alternate public APIs.

| CLI module | Function / explicit command alias | Arguments and options |
|---|---|---|
| [skills/advocates/__main__.py](../../skills/advocates/__main__.py) line 10 | `main` / (inferred by Typer) | `event: str=typer.Option(..., '--event', '-e', help='Short name of the event'), description: str=typer.Option(..., '--description', '-d', help='Detailed description of the event and skills required'), include: str=typer.Option(None, '--include', '-i', help='Comma-separated list of member IDs to restrict the search to'), exclude: str=typer.Option(None, '--exclude', '-x', help='Comma-separated list of member IDs to exclude'), top_k: int=typer.Option(10, '--top-k', '-k', help='Number of top advocates to return')` |
| [skills/bulk_refresh/__main__.py](../../skills/bulk_refresh/__main__.py) line 12 | `main` / (inferred by Typer) | `datasets: Optional[str]=typer.Option(None, '--datasets', '-d', help="Comma-separated source datasets, or 'all'. Defaults to active startup and community datasets."), skills: Optional[str]=typer.Option(None, '--skills', '-s', help="Comma-separated root skills, or 'all'. Required dependencies are included automatically.")` |
| [skills/dataset_chat/__main__.py](../../skills/dataset_chat/__main__.py) line 15 | `search_cmd` / 'search' | `dataset_name: str=typer.Argument(..., help='Name of the dataset/collection to search.'), query: str=typer.Argument('', help='The query/question to search for.')` |
| [skills/dataset_chat/__main__.py](../../skills/dataset_chat/__main__.py) line 35 | `chat_cmd` / 'chat' | `dataset_name: str=typer.Argument(..., help='Name of the dataset/collection to chat with.'), questions: str=typer.Argument(..., help='The query/question to ask.'), llm_instructions: Optional[str]=typer.Argument(None, help='Optional formatting/anti-hallucination instructions.')` |
| [skills/dataset_chat/__main__.py](../../skills/dataset_chat/__main__.py) line 57 | `sync_cmd` / 'sync' | `dataset_names: List[str]=typer.Argument(..., help='Names of the datasets/collections to sync. Can pass multiple separated by spaces.'), force: bool=typer.Option(False, '--force', help='Bypass the short in-process sync cache.')` |
| [skills/dataset_maintenance/__main__.py](../../skills/dataset_maintenance/__main__.py) line 35 | `diagnose` / (inferred by Typer) | `embeddings: Optional[str]=typer.Option(None, '--embeddings', '-e')` |
| [skills/dataset_maintenance/__main__.py](../../skills/dataset_maintenance/__main__.py) line 47 | `prune` / (inferred by Typer) | `embeddings: Optional[str]=typer.Option(None, '--embeddings', '-e'), apply: bool=typer.Option(False, '--apply', help='Delete orphaned dataset tenants. Default is dry-run.')` |
| [skills/dataset_maintenance/__main__.py](../../skills/dataset_maintenance/__main__.py) line 68 | `delete_command` / 'delete' | `dataset: Optional[str]=typer.Option(None, '--dataset', '-d'), embeddings: Optional[str]=typer.Option(None, '--embeddings', '-e')` |
| [skills/dataset_maintenance/__main__.py](../../skills/dataset_maintenance/__main__.py) line 81 | `rebuild_index_command` / 'rebuild-index' | `dataset: str=typer.Option(..., '--dataset', '-d'), sync: bool=typer.Option(True, '--sync/--no-sync', help='Re-index immediately after removing the dataset tenant.')` |
| [skills/dataset_maintenance/__main__.py](../../skills/dataset_maintenance/__main__.py) line 120 | `activate_command` / 'activate' | `dataset: str=typer.Option(..., '--dataset', '-d')` |
| [skills/dataset_maintenance/__main__.py](../../skills/dataset_maintenance/__main__.py) line 132 | `archive_command` / 'archive' | `dataset: str=typer.Option(..., '--dataset', '-d')` |
| [skills/dataset_maintenance/__main__.py](../../skills/dataset_maintenance/__main__.py) line 144 | `create_command` / 'create' | `startup_name: str=typer.Argument(..., help='Startup name for the new dossier.')` |
| [skills/dataset_maintenance/__main__.py](../../skills/dataset_maintenance/__main__.py) line 156 | `migrate_startup_dossiers_command` / 'migrate-startup-dossiers' | `apply: bool=typer.Option(False, '--apply', help='Apply the migration. Default is dry-run.'), manifest: str=typer.Option('startup-dossier-migration.json', '--manifest')` |
| [skills/dataset_maintenance/__main__.py](../../skills/dataset_maintenance/__main__.py) line 184 | `migrate_insight_manifests_command` / 'migrate-insight-manifests' | `apply: bool=typer.Option(False, '--apply', help='Adopt reconstructable insight files. Default is dry-run.')` |
| [skills/dataset_maintenance/__main__.py](../../skills/dataset_maintenance/__main__.py) line 204 | `dataset_from_insight_command` / 'dataset-from-insight' | `target_dataset: str=typer.Option(..., '--target-dataset', help='Generated dataset to reconcile.'), source_datasets: Optional[str]=typer.Option(None, '--source-datasets', '--source-dataset', help='Comma-separated source datasets. Omit to search all.'), skill: str=typer.Option(..., '--skill', help='Insight skill to collect, e.g. person_profile.'), dry_run: bool=typer.Option(False, '--dry-run', help='Report what would change without writing files.')` |
| [skills/dd_checks/__main__.py](../../skills/dd_checks/__main__.py) line 14 | `run_dd_checks` / (inferred by Typer) | `startup: str=typer.Option(..., '--startup', '-s', help='Name of the startup')` |
| [skills/dd_priorities/__main__.py](../../skills/dd_priorities/__main__.py) line 14 | `run_dd_priorities` / (inferred by Typer) | `startup: str=typer.Option(..., '--startup', '-s', help='Name of the startup')` |
| [skills/dealum_import/__main__.py](../../skills/dealum_import/__main__.py) line 12 | `main` / (inferred by Typer) | `startup: str` |
| [skills/deep_dive_invitation/__main__.py](../../skills/deep_dive_invitation/__main__.py) line 15 | `main` / (inferred by Typer) | `startup: str=typer.Option(..., '--startup', '-s', help='Exact Dealum name or code.'), founders: str=typer.Option('', '--founders', help='Comma-separated founders as Name <email>, email, or name.'), investors: str=typer.Option('', '--investors', help='Comma-separated investors as Name <email>, email, or name.')` |
| [skills/expert_search/__main__.py](../../skills/expert_search/__main__.py) line 11 | `main` / (inferred by Typer) | `startup: str=typer.Option(..., '--startup', '-s', help='Name of the startup'), include: str=typer.Option(None, '--include', '-i', help='Comma-separated list of expert IDs to restrict the search to'), exclude: str=typer.Option(None, '--exclude', '-x', help='Comma-separated list of expert IDs to exclude'), top_k: int=typer.Option(8, '--top-k', '-k', help='Number of top experts to return')` |
| [skills/harness/__main__.py](../../skills/harness/__main__.py) line 32 | `main` / (inferred by Typer) | `command: Optional[List[str]]=typer.Argument(None, help='Optional one-shot slash command, for example: /help or /startup_profile avientus.')` |
| [skills/investor_profile/__main__.py](../../skills/investor_profile/__main__.py) line 11 | `main` / (inferred by Typer) | `source_dataset: str=typer.Option('sictic-members', '--source-dataset', help='Community dataset containing person profiles and track records.'), person: str \| None=typer.Option(None, '--person', '-p', help='Comma-separated person names; omit to build profiles for all members.')` |
| [skills/linkedin_maintenance/__main__.py](../../skills/linkedin_maintenance/__main__.py) line 25 | `missing` / (inferred by Typer) | `none` |
| [skills/linkedin_maintenance/__main__.py](../../skills/linkedin_maintenance/__main__.py) line 31 | `import_command` / 'import' | `file_path: str=typer.Argument(...), dataset: Optional[str]=typer.Option(None, '--dataset', '-d')` |
| [skills/linkedin_maintenance/__main__.py](../../skills/linkedin_maintenance/__main__.py) line 43 | `diagnose` / (inferred by Typer) | `none` |
| [skills/llm_chat/__main__.py](../../skills/llm_chat/__main__.py) line 16 | `main` / (inferred by Typer) | `prompt: str=typer.Argument(..., help='The prompt/message you want to send to the LLM.')` |
| [skills/member_preferences/__main__.py](../../skills/member_preferences/__main__.py) line 15 | `main` / (inferred by Typer) | `dataset: str=typer.Option('sictic-members', '--dataset', '-d', help='Member dataset to enrich.')` |
| [skills/person_profile/__main__.py](../../skills/person_profile/__main__.py) line 12 | `main` / (inferred by Typer) | `dataset: str=typer.Option(..., '--dataset', '-d', help='The target dataset to search.'), person: Optional[str]=typer.Option(None, '--person', '-p', help='Comma-separated person names to profile; omit it to profile everyone in the dataset.')` |
| [skills/persons_in_dataset/__main__.py](../../skills/persons_in_dataset/__main__.py) line 10 | `main` / (inferred by Typer) | `dataset: str=typer.Option(..., '--dataset', '-d')` |
| [skills/potential_investors/__main__.py](../../skills/potential_investors/__main__.py) line 11 | `main` / (inferred by Typer) | `startup: str=typer.Option(..., '--startup', '-s', help='The name of the startup to match.'), include: str=typer.Option(None, '--include', '-i', help='Comma-separated list of investor names to include.'), exclude: str=typer.Option(None, '--exclude', '-x', help='Comma-separated list of investor names to exclude.'), top_k: int=typer.Option(8, '--top-k', '-k', help='Number of top investors to return.')` |
| [skills/ranking/__main__.py](../../skills/ranking/__main__.py) line 11 | `main` / (inferred by Typer) | `target: str=typer.Option('persons', '--target', '-t', help='What entity to rank'), objective: str=typer.Option(..., '--objective', '-o', help='The objective/criteria for ranking'), top_k: int=typer.Option(8, '--top-k', '-k', help='Number of top candidates to return')` |
| [skills/sha_review/__main__.py](../../skills/sha_review/__main__.py) line 14 | `run_sha_review` / (inferred by Typer) | `dataset_name: str=typer.Option(..., '--dataset', '-d', help='Target startup dataset name.')` |
| [skills/startup_profile/__main__.py](../../skills/startup_profile/__main__.py) line 54 | `profile_startup` / (inferred by Typer) | `startup: str=typer.Option(..., '--startup', '-s', help='Comma-separated startup names'), files: Optional[List[str]]=typer.Option(None, '--files', '-f', help='Optional list of PDF/document files')` |
| [skills/startup_traction/__main__.py](../../skills/startup_traction/__main__.py) line 11 | `main` / (inferred by Typer) | `startup: str=typer.Option(..., '--startup', '-s', help='The name of the startup to analyze.')` |
| [skills/startup_website_import/__main__.py](../../skills/startup_website_import/__main__.py) line 16 | `main` / (inferred by Typer) | `startup_name: str=typer.Argument(..., help='Startup name for the dataset.'), url: str=typer.Argument(..., help='Public startup website URL.'), depth: int=typer.Option(1, '--depth', min=0, help='Internal crawl depth.'), max_pages: int=typer.Option(50, '--max-pages', min=1, help='Maximum HTML pages to import.'), include_pdfs: bool=typer.Option(True, '--pdfs/--no-pdfs', help='Download same-domain PDFs linked from crawled pages.'), max_pdfs: int=typer.Option(20, '--max-pdfs', min=0, help='Maximum PDF files to download.'), max_pdf_mb: int=typer.Option(25, '--max-pdf-mb', min=1, help='Maximum size per PDF download.'), respect_robots: bool=typer.Option(True, '--respect-robots/--ignore-robots', help='Respect robots.txt when available.')` |
| [skills/submission_ready/__main__.py](../../skills/submission_ready/__main__.py) line 16 | `run_submission_ready` / (inferred by Typer) | `startup: Optional[list[str]]=typer.Option(None, '--startup', '-s', help='Startup name. Repeat for multiple startups; omit to process all Application and Under review submissions.')` |
| [skills/suggested_startups/__main__.py](../../skills/suggested_startups/__main__.py) line 13 | `main` / (inferred by Typer) | `startups: Optional[List[str]]=typer.Option(None, '--startups', '-s', help='List of startup names. If omitted, discovered from insights.'), investor: Optional[str]=typer.Option(None, '--investor', '-i', help='Comma-separated investor names. If omitted, investors are discovered from insights.'), max_startups: int=typer.Option(5, '--max-startups', '-m', help='Maximum number of startups to suggest per investor.')` |
| [skills/team_profile/__main__.py](../../skills/team_profile/__main__.py) line 12 | `profile_team` / (inferred by Typer) | `startup: str=typer.Option(..., '--startup', '-s', help='Name of the startup')` |
| [skills/team_profile_revised/__main__.py](../../skills/team_profile_revised/__main__.py) line 12 | `run_team_profile_revised` / (inferred by Typer) | `dataset_name: str=typer.Option(..., '--dataset', '-d', help='Target startup dataset.')` |

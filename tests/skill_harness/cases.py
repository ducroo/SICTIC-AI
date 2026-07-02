ADMIN_ONLY_HARNESS_COMMANDS = {
    "/config",
    "/sync",
    "/dealum_import",
}

SKILL_COVERAGE = {
    "advocates": "local-smoke",
    "batch_audit": "local-smoke",
    "bulk_refresh": "existing-unit",
    "config_load": "existing-unit",
    "dataset_chat": "harness-smoke",
    "dataset_maintenance": "utility-smoke",
    "dd_checks": "local-smoke",
    "dealum_import": "utility-smoke",
    "expert_search": "local-smoke",
    "gdrive_sync": "contract-admin",
    "harness": "existing-unit",
    "investor_profile": "local-smoke",
    "linkedin_maintenance": "utility-smoke",
    "llm_chat": "utility-smoke",
    "person_profile": "local-smoke",
    "potential_investors": "local-smoke",
    "ranking": "utility-smoke",
    "sictic_git_sync": "existing-unit",
    "standards_and_architecture": "docs-only",
    "startup_profile": "local-smoke",
    "startup_traction": "local-smoke",
    "startup_website_import": "utility-smoke",
    "suggested_startups": "local-smoke",
    "team_profile": "local-smoke",
}

SKILL_COVERAGE_REASONS = {
    "contract-admin": "Operational skill with external or destructive side effects; covered by import/CLI contracts and focused existing tests.",
    "docs-only": "Instruction-only skill package; import and SKILL.md contracts are the behavioral surface.",
    "existing-unit": "Covered by existing focused tests outside the skill harness suite.",
    "harness-smoke": "Covered through the slash-command harness with mocked service boundaries.",
    "local-smoke": "Runs against local temp datasets with external services mocked.",
    "utility-smoke": "Covered by deterministic local unit/smoke tests for cheap public behavior.",
}

HARNESS_SMOKE_COMMANDS = {
    "/dataset_chat": "/dataset_chat example-startup What is the fixture?",
    "/startup_profile": "/startup_profile example-startup",
    "/startup_traction": "/startup_traction example-startup",
    "/batch_audit": "/batch_audit example-startup {checklist}",
    "/person_profile": "/person_profile sictic-members Jane Doe",
    "/team_profile": "/team_profile example-startup",
    "/investor_profile": "/investor_profile --source-dataset sictic-members",
    "/expert_search": "/expert_search example-startup",
    "/potential_investors": "/potential_investors example-startup",
    "/advocates": "/advocates fixture-event --description Fixture event",
    "/suggested_startups": (
        "/suggested_startups --startups example-startup "
        "--investors Jane Doe --max-startups 1"
    ),
    "/dd_checks": "/dd_checks example-startup",
}

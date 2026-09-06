ADMIN_ONLY_HARNESS_COMMANDS = {
    "/config",
    "/sync",
    "/dealum_import",
}

SKILL_COVERAGE = {
    "advocates": "local-smoke",
    "bulk_refresh": "existing-unit",
    "captable_analysis": "harness-smoke",
    "captable_build": "harness-smoke",
    "submission_ready": "local-smoke",
    "dataset_chat": "harness-smoke",
    "dataset_maintenance": "utility-smoke",
    "deep_dive_invitation": "local-smoke",
    "dd_checks": "local-smoke",
    "dd_priorities": "local-smoke",
    "dealum_import": "utility-smoke",
    "expert_search": "local-smoke",
    "harness": "existing-unit",
    "investor_profile": "local-smoke",
    "linkedin_maintenance": "utility-smoke",
    "llm_chat": "utility-smoke",
    "member_preferences": "utility-smoke",
    "person_profile": "local-smoke",
    "persons_in_dataset": "existing-unit",
    "potential_investors": "local-smoke",
    "ranking": "utility-smoke",
    "sha_review": "local-smoke",
    "standards_and_architecture": "docs-only",
    "startup_profile": "local-smoke",
    "startup_traction": "local-smoke",
    "startup_website_import": "utility-smoke",
    "suggested_startups": "local-smoke",
    "team_profile": "local-smoke",
    "team_profile_revised": "local-smoke",
}

SKILL_COVERAGE_REASONS = {
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
    "/persons_in_dataset": "/persons_in_dataset sictic-members",
    "/person_profile": "/person_profile sictic-members Jane Doe",
    "/team_profile": "/team_profile example-startup",
    "/team_profile_revised": "/team_profile_revised example-startup",
    "/investor_profile": "/investor_profile --source-dataset sictic-members",
    "/expert_search": "/expert_search example-startup",
    "/potential_investors": "/potential_investors example-startup",
    "/member_preferences": "/member_preferences",
    "/deep_dive_invitation": (
        "/deep_dive_invitation --startup example-startup "
        "--founders Jane <jane@example.com>"
    ),
    "/advocates": "/advocates fixture-event --description Fixture event",
    "/suggested_startups": (
        "/suggested_startups --startups example-startup "
        "--investor Jane Doe --max-startups 1"
    ),
    "/dd_checks": "/dd_checks example-startup",
    "/dd_priorities": "/dd_priorities example-startup",
    "/submission_ready": "/submission_ready example-startup",
    "/sha_review": "/sha_review example-startup",
    "/captable_build": "/captable_build example-startup",
    "/captable_analysis": "/captable_analysis example-startup",
}

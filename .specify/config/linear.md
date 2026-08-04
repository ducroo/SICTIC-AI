# Linear Integration Configuration

This file defines the configuration for the Spec Kit Linear integration.
All speckit skills read this file at runtime to determine how to interact with Linear.

## MCP Server

- **Server name**: `linear` (as configured via `claude mcp add -s user --transport http linear https://mcp.linear.app/mcp`)
- **Transport**: HTTP (Streamable HTTP)
- All Linear operations use the official Linear MCP server tools prefixed with `mcp__linear__`

## Linear Team

- Skills use `list_teams` to discover the active team at runtime
- If multiple teams exist, the agent asks the user which team to use
- The selected team ID is used for all `create_issue` calls

## Product Project

All features live in a single **product project** in Linear. The constitution project remains separate.

- **Product project name**: `SICTIC-AI`
- Skills discover the product project via `list_projects` by name
- If the product project does not exist yet, the creator skill (`speckit-specify` or `speckit-baseline`) asks the user for the product project name and creates it via `create_project`
- Once set, all subsequent skills reuse this project for every feature

## Label Convention

All speckit labels follow the `speckit:*` naming pattern. Feature labels follow the `feature:*` pattern. Skills will attempt to find existing labels and create them if missing.

### Required Labels

| Label Name             | Purpose                                           |
| ----------------------- | ------------------------------------------------- |
| `speckit:spec`         | Feature specification document issue              |
| `speckit:plan`         | Implementation plan document issue                |
| `speckit:research`     | Technical research document issue                 |
| `speckit:data-model`   | Entity definitions document issue                 |
| `speckit:quickstart`   | Integration guide document issue                  |
| `speckit:contract`     | API contract document issue                       |
| `speckit:checklist`    | Quality validation checklist issue                |
| `speckit:task`         | Implementation task issue                         |
| `speckit:constitution` | Project constitution document issue               |
| `project:sictic-ai`    | Scopes an issue in the shared speckit-constitution project to this repo |
| `parallelizable`       | Task can be executed in parallel with other tasks |

### Feature Labels

Each feature gets a dedicated label with the pattern `feature:NNN-short-name`:

| Label Name               | Purpose                                                                              |
| ------------------------ | ------------------------------------------------------------------------------------ |
| `feature:NNN-short-name` | Groups all issues belonging to one feature (e.g., `feature:001-claude-llm-backend`) |

- Every issue created by a speckit skill gets **both** a `speckit:*` type label **and** a `feature:*` label (dual labeling)
- Feature numbers are auto-incremented by scanning existing `feature:*` labels via `list_issue_labels`
- Feature labels are created via `create_issue_label` when a new feature is specified

## Feature Naming Convention

- **Constitution project**: `speckit-constitution` (singleton, shared across all repos in this workspace — scope to this repo via the `project:sictic-ai` label)
- **Product project**: `SICTIC-AI` — a single project holding all feature issues
- **Feature identifier**: `NNN-short-name` (e.g., `001-user-auth`, `002-payment-flow`) — encoded as a label, not a project

## Data Model Mapping

| Speckit Concept           | Linear Entity                                         | Identifier                                        |
| -------------------------- | ------------------------------------------------------ | --------------------------------------------------- |
| Product                   | Project (single, shared)                              | Product project name                              |
| Feature (`001-user-auth`) | Label `feature:001-user-auth`                         | Label on all feature issues                       |
| `spec.md`                 | Issue (title: `[SPEC] NNN: Feature Name`)             | Labels: `speckit:spec` + `feature:NNN-name`       |
| `plan.md`                 | Issue (title: `[PLAN] NNN: Implementation Plan`)      | Labels: `speckit:plan` + `feature:NNN-name`       |
| `research.md`             | Issue (title: `[RESEARCH] NNN: Technical Research`)   | Labels: `speckit:research` + `feature:NNN-name`   |
| `data-model.md`           | Issue (title: `[DATA-MODEL] NNN: Entity Definitions`) | Labels: `speckit:data-model` + `feature:NNN-name` |
| `quickstart.md`           | Issue (title: `[QUICKSTART] NNN: Integration Guide`)  | Labels: `speckit:quickstart` + `feature:NNN-name` |
| `contracts/api.yaml`      | Issue (title: `[CONTRACT] NNN: API Contract`)         | Labels: `speckit:contract` + `feature:NNN-name`   |
| `checklists/*.md`         | Issue (title: `[CHECKLIST] NNN: {domain}`)            | Labels: `speckit:checklist` + `feature:NNN-name`  |
| Constitution              | Issue in `speckit-constitution` project               | Labels: `speckit:constitution` + `project:sictic-ai` |
| Task phases               | Milestones in product project                         | Milestone name: `NNN: Phase X: Name`              |
| Individual tasks          | Issues in product project                             | Labels: `speckit:task` + `feature:NNN-name`       |
| Task `[P]` marker         | Additional label on task issue                        | Label: `parallelizable`                           |
| Task completion `[X]`     | Issue status set to "Done"                            | Status workflow                                   |
| Task priority P1/P2/P3    | Issue priority (1=Urgent, 2=High, 3=Medium)           | Priority field                                    |
| Task dependencies         | Documented in issue description                       | Text: "Depends on: T003, T005"                    |

## Find Active Feature Pattern

Each skill that needs to locate the current feature uses this shared pattern:

1. **Read product project name** from this config file. If empty or placeholder, ask the user for the product project name and record it.
2. **Determine feature identifier**:
   a. If user specifies a feature name/number (e.g., `001` or `001-user-auth`), use it directly
   b. If on a git branch matching `NNN-*`, extract the feature identifier from the branch name
   c. Otherwise, list `feature:*` labels via `list_issue_labels`, present them to the user, and ask which feature to use
3. **Find product project** via `list_projects` matching the product project name
4. **If product project not found**: ERROR "Product project 'SICTIC-AI' not found in Linear. Check `.specify/config/linear.md`."
5. **Query issues** via `list_issues(project=<product-project>, label="feature:NNN-name")` to find all issues for the feature
6. **Filter by title prefix** for the specific artifact type (`[SPEC]`, `[PLAN]`, etc.)
7. **If required artifact missing**: ERROR "Required artifact missing. Run speckit-{phase} first."
8. **Fallback (backwards compatibility)**: If no feature label matches, check for a legacy `NNN-*` project via `list_projects`. If found, use it as the feature project (read-only compatibility with old layout).

## Authentication

- Linear MCP server handles OAuth authentication automatically
- If auth fails mid-workflow, the skill should display a clear error and instruct the user to re-authenticate via the MCP server configuration
- Never fall back to local file storage if Linear is unavailable

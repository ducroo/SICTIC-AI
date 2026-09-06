# Codebase Assessment

Historical review of an earlier PR. The implementation observations below may
have been superseded. Use [current standards](../skills/standards_and_architecture/SKILL.md)
and [the documentation review status](reviews/documentation-closeout-2026-09-06.md)
for current contracts and outstanding decisions; this review is not an instruction
to implement its proposed packaging or refactors.

## Summary

The repository is organized around user-facing `skills/` packages and shared
`lib/` infrastructure, with tests covering many core workflows. The current
highest-risk architectural issue is packaging: runtime imports and config
loading still assume the source repository is on `sys.path` through the
installer-generated `.pth` file. That should be handled in the separate
self-contained installer PR.

This assessment PR keeps changes low risk and removes a repo-owned Pydantic v2
deprecation warning.

## Findings

### Fixed in this PR

- `skills.ranking.ranking_top_k.RankedProfilesResult` used deprecated Pydantic
  `Config`; it now uses `ConfigDict`.

### Follow-up risks

- Package import ambiguity exists in several skill packages where
  `skills.<name>.__init__` exports functions with the same name as submodules.
  This can confuse tests and monkeypatching. Prefer importing submodules with
  `importlib.import_module(...)` until a broader export policy is chosen.
- Many business skills catch broad `Exception` and rethrow generic
  `RuntimeError` or continue with partial output. This is sometimes intentional
  for batch workflows, but it makes operational failures harder to classify.
- Several modules still read `REPO_PATH` directly for config and runtime files.
  The packaging PR should decide whether installed code treats the install
  directory as `REPO_PATH` or introduces a separate application root.
- Optional Google Drive synchronization remains external to the Python runtime;
  general storage code should continue to operate on local files only.

## Recommended Next PRs

- Self-contained installer packaging: copy `skills`, `lib`, `config`,
  `scripts`, and support files into the install root; point `.pth` at that
  installed root; create an installed `.env` from `.env-template` without
  copying secrets by default.
- Error-boundary cleanup: replace broad catches in high-value paths with
  typed exceptions or structured result objects where failures need to be
  actionable.
- Import policy cleanup: remove or standardize package-level function exports
  that shadow submodule names.

# Repository working instructions

## Read the standards first

Before modifying code, read
`skills/standards_and_architecture/SKILL.md`
and the documentation for the affected skills.

The standards skill is the authoritative reference for repository
conventions. Do not duplicate or redefine those conventions here.

## Scope and approval

Clarify unresolved requirements before editing. Ask before changing
skills outside the agreed scope or changing established contracts.
Approval already given does not need to be requested again.

## Preserve existing contracts

A request to add or fix functionality does not authorize changing
established conventions.

Preserve person identity and matching, filenames, storage layout,
manual-input precedence, cache behavior, public APIs, and registry
orchestration unless the user explicitly authorizes a change.

Before editing:

- Inspect the canonical shared implementation and its callers.
- Inspect a comparable existing skill and relevant tests.
- Check Git history when the intended convention is unclear.

If documentation and established behavior conflict, explain the
specific conflict before changing the affected contract. Do not
silently choose a new convention.

## Reuse shared implementations

Use the repository's existing abstractions for identity, matching,
paths, insight lifecycle, configuration, and orchestration.

Do not introduce local replacements, alternate discovery paths,
filename variants, or generation modes without checking how they
interact with existing consumers and caches.

## Verify compatibility

Run tests appropriate to the changed behavior.

Put lasting regression coverage in pytest rather than leaving temporary
verification scripts.

For changes affecting shared contracts, add or retain regression
coverage based on the established behavior. Do not change test
expectations merely to make a new implementation pass.

Review the complete diff before finishing. Check for unintended
changes to conventions, callers, configuration, and documentation.

Report what changed, what was verified, and any remaining
compatibility risks.

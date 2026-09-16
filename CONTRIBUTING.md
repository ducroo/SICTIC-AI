# Contributing

Read [AGENTS.md](AGENTS.md) for scope and review procedures and the
[standards and architecture skill](skills/standards_and_architecture/SKILL.md)
for technical contracts. Read the affected skill's `SKILL.md` before changing
its behavior. These are the authoritative references; this guide does not
maintain a second API catalogue.

## Scope and shared implementations

Start from current `main`, or compare your branch with it before proposing
changes. A maintainer request or an agreed issue provides the scope; a separate
issue is not required for every change. Existing code may be refactored within
that scope. Ask about unresolved requirements or contract changes, without
repeating approval already given.

Search `skills/` and `lib/` for existing capabilities before adding one. Verify
routine names, signatures and side effects against their implementation and
callers. Follow the standards' ownership boundaries: compose public skill APIs
for workflows and shared libraries for their documented primitives. Explicit
object-returning adapters should reuse the same underlying workflow.

Keep changes focused and explain affected consumers when modifying shared
behavior. Preserve contracts unless their change has been agreed. Update the
owning documentation instead of copying its rules into another guide.

## Validation

Run validation appropriate to the change:

- Documentation: check accuracy, referenced APIs and links.
- CLI changes: check argument parsing and forwarding to the public API.
- Identity, storage or other shared contracts: retain or add regression coverage
  for the established behavior and affected consumers.
- Extraction or assessment prompts: evaluate representative dossier evidence
  and inspect the resulting output when validating model behavior.

Use the `sictic-env` environment described in
[environment.yml](environment.yml) and the [installer](install.sh). From the
repository root, run the non-live suite with:

```sh
python -m pytest -q -m "not live"
```

GitHub Actions runs this suite on pull requests and pushes to `main`.
Live service or paid model runs are not required for every change. State what
was checked, what was not checked, and any remaining uncertainty; mocked tests
alone do not establish model output quality. Do not weaken tests to hide failures.

## Pull requests

Explain the problem and resulting behavior, the existing implementations reused,
the validation performed and any risks or unverified behavior. Update relevant
skill documentation and configuration when behavior changes. Include CLI,
harness, registry and artifact compatibility checks when the change affects
those contracts, as described in the standards.

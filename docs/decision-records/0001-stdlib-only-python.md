# ADR-0001: Stdlib-only Python runtime

**Status:** Accepted
**Last reviewed:** 2026-06-02

## Context

`drift-gate` is a composite GitHub Action whose hot path runs once per consumer
PR. Every Python dependency that is not pre-installed on the runner adds a
`pip install` step. For a quality gate that should be transparent, that overhead
competes directly with its value.

GitHub-hosted runners (`ubuntu-latest`) ship Python 3.12 with the full standard
library. No additional installation is needed for json, pathlib, hashlib,
difflib, subprocess, and similar modules.

The alternative — allowing third-party dependencies for richer output, schema
validation, or HTTP client handling — would require either:

1. A `setup-python` + `pip install` step on each consumer CI run (~15 s), or
2. A pre-built Docker container image pinned to a digest (added maintenance
   surface, pull latency, and trust boundary).

## Decision

The `drift-gate` runtime (`tools/baseline/`) uses only the Python standard
library. No third-party packages are imported. This constraint is enforced by
keeping `dependencies = []` in `pyproject.toml` and by the CI smoke-test job,
which installs only the package (no extras) before running the CLI.

Dev-only dependencies (`pytest`, `ruff`) are declared under
`[project.optional-dependencies] dev` and are never installed on the consumer's
runner hot path.

## Consequences

- Consumer CI runs invoke the action with zero pip overhead.
- The action can never rely on requests, httpx, pydantic, jsonschema, or any
  other popular library. GitHub API calls are delegated to the `gh` CLI (already
  on all GitHub-hosted runners) rather than made directly from Python.
- Manifest validation, diff generation, and Check Run serialization are all
  implemented against stdlib primitives. The stdlib constraint is a forcing
  function that keeps the implementation small.
- If a future feature genuinely cannot be implemented with stdlib alone, this
  ADR must be revisited and the build must add an explicit `pip install` step
  with a pinned version and a `# renovate:` annotation so Renovate can track it.

# drift-gate

A composite GitHub Action that detects when files in a consumer repository
have drifted from a canonical source. Reports per-file pass/fail via the
GitHub Check Runs API — failures appear inline in the PR's "Files changed"
view, not buried in a comment — and fails the step on any drift so a
repository ruleset can require it as a merge gate.

## When to use this

Use `drift-gate` when you have a **canonical source of truth** for certain
files, and you want **byte-identical mirrors** in some number of consumer
repos. Common examples:

- An org-level `.github` repo whose ADRs should be mirrored byte-for-byte
  into every repo's `docs/decision-records/org/`.
- A per-language template repo whose `Makefile`, `pyproject.toml`,
  `.editorconfig`, etc. should be mirrored byte-for-byte into every
  consumer of that language.
- A security baseline (`SECURITY.md`, OPA policies, security workflows)
  whose drift you want to catch on every PR before merge.

`drift-gate` is **not** for fuzzy matches, schema validation, or policy
evaluation. It compares bytes. If the bytes differ, the gate fails. If
you want OPA / Conftest / Sentinel, use those.

## Usage

```yaml
name: Quality Gates

on:
  pull_request:
    branches: [main]

permissions:
  contents: read
  checks: write

jobs:
  drift:
    runs-on: ubuntu-latest
    steps:
      - uses: NWarila/drift-gate@<sha>
        with:
          source-repo: nwarila-platform/.github
          source-ref: ${{ github.event.repository.fork && 'main' || github.sha }}
          manifest: drift-manifest.json
          check-name: org-baseline / verify
```

Multiple sources in one job — the action composes; call it once per source:

```yaml
jobs:
  drift:
    runs-on: ubuntu-latest
    steps:
      - name: Org baseline
        uses: NWarila/drift-gate@<sha>
        with:
          source-repo: nwarila-platform/.github
          source-ref: <pinned-sha-of-org-repo>
          manifest: baseline-manifest.json
          check-name: org-baseline / verify

      - name: Type-template baseline
        uses: NWarila/drift-gate@<sha>
        with:
          source-repo: NWarila/terraform-runner-template
          source-ref: <pinned-sha-of-template>
          manifest: drift-manifest.json
          check-name: type-template-baseline / verify
```

Each invocation produces an independent Check Run on the PR; both must
pass for any branch protection rule that requires both.

## Inputs

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `source-repo` | yes | — | Canonical source repo, in `owner/repo` form. |
| `source-ref` | yes | — | Git ref (SHA, branch, or tag) of source-repo. SHA-pin for reproducibility. |
| `manifest` | no | `drift-manifest.json` | Path within `source-repo` to the JSON manifest. |
| `consumer-ref` | no | PR head SHA, or `github.sha` | Git ref of the consumer to check. |
| `check-name` | no | `drift-gate / verify` | Name displayed for the GitHub Check Run. |
| `github-token` | no | `${{ github.token }}` | Token used to POST Check Runs. |

## Outputs

| Output | Description |
| --- | --- |
| `passed` | `"true"` if every manifest file is byte-identical with source; `"false"` otherwise. |

## The manifest

A JSON file in `source-repo` enumerating which files must be mirrored. Version
1 is the compact byte-identical-only schema:

```json
{
  "version": "1",
  "files": [
    {
      "source": "path/in/source/repo.md",
      "target": "path/in/consumer/repo.md"
    },
    {
      "source": "docs/decision-records/0001-foo.md",
      "target": "docs/decision-records/org/0001-foo.md"
    }
  ]
}
```

`source` is the path within `source-repo`; `target` is the path within
the consumer repo where the byte-identical copy must exist. Source path
== target path is the common case (use the same string twice).

Version 2 makes the propagation semantics explicit:

```json
{
  "version": "2",
  "byte_identical": [
    {
      "source": "policies/opa/terraform_plan.rego",
      "target": "policies/opa/terraform_plan.rego"
    }
  ],
  "scaffold_starter": [
    {
      "source": "policies/opa/synthetic_framework_plan.rego",
      "target": "policies/opa/synthetic_framework_plan.rego"
    }
  ]
}
```

`byte_identical` entries are enforced exactly like v1 `files` entries.
`scaffold_starter` entries are validated for shape and duplicate targets but
are not compared. Use them to document starter files that consumers are
expected to rewrite, not mirror.

The manifest is validated on load with stdlib-only checks, so unknown keys,
path traversal, absolute paths, duplicate targets, and unsupported versions all
fail loudly instead of silently mis-comparing.

## Reporting

`drift-gate` reports via the GitHub Check Runs API, producing one Check
Run per invocation with one annotation per non-passing file. Annotations
appear inline on the offending file in the PR's "Files changed" tab.

Per-file statuses:

| Status | Meaning |
| --- | --- |
| `MATCH` | Byte-identical with source. |
| `DRIFT` | File exists but content differs from source. |
| `MISSING` | File listed in manifest but absent from consumer. |
| `SOURCE_MISSING` | File listed in manifest but absent from `source-repo` (manifest bug — fix the manifest). |

The Check Run's `conclusion` is `success` iff every entry is `MATCH`,
`failure` otherwise. Branch protection / repository rulesets requiring
`drift-gate / verify` (or your `check-name`) can use this directly.

## Local use

You can also run the underlying CLI locally without the action:

```sh
pip install git+https://github.com/NWarila/drift-gate
drift-gate \
  --consumer-root path/to/consumer \
  --source-root path/to/source \
  --manifest path/to/source/drift-manifest.json \
  --output-mode markdown
```

`--output-mode` accepts `markdown`, `json`, or `check-run` (the last
requires `--head-sha` and `--repo` and POSTs to the GitHub Check Runs
API via the `gh` CLI).

## Why composite

`drift-gate` is a composite action so that a single CI job can call it
multiple times against different sources, sharing one runner setup.
A reusable workflow would force one job per source, doubling cold-start
cost. If you also want it as a merge gate, wrap one invocation in a
reusable workflow and reference that workflow from a repository ruleset.

## License

MIT — see [LICENSE](LICENSE).

"""CLI entry point.

Usage in CI:
    python -m baseline.cli \
      --consumer-root consumer \
      --source-root source \
      --manifest source/drift-manifest.json \
      --output-mode check-run \
      --head-sha "$HEAD_SHA" \
      --repo "$REPO" \
      --source-repo "$SOURCE_REPO" \
      --source-ref "$SOURCE_REF" \
      --gate-version "$GATE_VERSION" \
      --check-name "drift-gate / verify"

Usage locally (no GitHub API):
    python -m baseline.cli \
      --consumer-root path/to/consumer \
      --source-root path/to/source \
      --manifest path/to/source/drift-manifest.json \
      --output-mode markdown
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .check import overall_passed, run_check
from .manifest import load_manifest
from .report import ReportContext, to_check_run_payload, to_json, to_markdown


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="drift-gate",
        description=(
            "Detect when files in a consumer repo have drifted from a canonical "
            "source repo. Compares byte-for-byte against a manifest of expected "
            "file mappings; fails non-zero on any drift."
        ),
    )
    p.add_argument(
        "--consumer-root",
        type=Path,
        required=True,
        help="Filesystem path to the consumer (the repo being checked).",
    )
    p.add_argument(
        "--source-root",
        type=Path,
        required=True,
        help="Filesystem path to the canonical source repo.",
    )
    p.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Path to the JSON manifest enumerating files to enforce.",
    )
    p.add_argument(
        "--output-mode",
        choices=("json", "markdown", "check-run"),
        default="markdown",
        help="What to emit on stdout. check-run also POSTs to GitHub Check Runs API.",
    )
    p.add_argument(
        "--head-sha",
        help="PR head SHA (required for check-run mode).",
    )
    p.add_argument(
        "--repo",
        help='Consumer repo in "owner/repo" form (required for check-run mode).',
    )
    p.add_argument(
        "--source-repo",
        help='Canonical source repo in "owner/repo" form (presentational).',
    )
    p.add_argument(
        "--source-ref",
        help="Git ref / SHA of the canonical source the consumer was checked against.",
    )
    p.add_argument(
        "--gate-version",
        help="SHA / ref of the drift-gate action itself (shown in summary footer).",
    )
    p.add_argument(
        "--check-name",
        default="drift-gate / verify",
        help='Display name of the GitHub Check Run (default: "drift-gate / verify").',
    )
    p.add_argument(
        "--step-summary",
        type=Path,
        default=None,
        help=(
            "If set, also append the markdown report to this path (typically $GITHUB_STEP_SUMMARY)."
        ),
    )
    return p


def _post_check_run(repo: str, payload: dict) -> None:
    """POST the Check Run via gh CLI (uses GITHUB_TOKEN from env)."""
    body = json.dumps(payload)
    subprocess.run(
        ["gh", "api", "-X", "POST", f"repos/{repo}/check-runs", "--input", "-"],
        input=body,
        text=True,
        check=True,
    )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    manifest = load_manifest(args.manifest)
    results = run_check(manifest, args.source_root, args.consumer_root)
    passed = overall_passed(results)

    ctx = ReportContext(
        source_repo=args.source_repo,
        source_ref=args.source_ref,
        consumer_repo=args.repo,
        consumer_ref=args.head_sha,
        gate_version=args.gate_version,
    )

    md = to_markdown(results, ctx=ctx)
    if args.step_summary is not None and str(args.step_summary):
        with args.step_summary.open("a", encoding="utf-8") as fh:
            fh.write(md + "\n")

    if args.output_mode == "json":
        print(to_json(results, ctx=ctx))
    elif args.output_mode == "markdown":
        print(md)
    elif args.output_mode == "check-run":
        if not args.head_sha or not args.repo:
            print("error: --head-sha and --repo required for check-run mode", file=sys.stderr)
            return 2
        payload = to_check_run_payload(
            results,
            head_sha=args.head_sha,
            name=args.check_name,
            ctx=ctx,
        )
        _post_check_run(args.repo, payload)
        # Also print markdown to job log for grepability.
        print(md)

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())

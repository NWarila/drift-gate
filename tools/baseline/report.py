"""Output formatters.

Three formats:
  - JSON  — machine-readable; for piping to other tools.
  - Markdown — human-readable; written to GITHUB_STEP_SUMMARY.
  - Check Runs API payload — submitted to GitHub for inline annotations.
"""

from __future__ import annotations

import json
from typing import Any

from .check import CheckResult, ResultStatus

_STATUS_GLYPH = {
    ResultStatus.MATCH: "✅",
    ResultStatus.DRIFT: "❌",
    ResultStatus.MISSING: "⚠️",
    ResultStatus.SOURCE_MISSING: "🛑",
}


def to_json(results: list[CheckResult]) -> str:
    """Stable JSON output suitable for diff and piping."""
    payload = {
        "results": [
            {
                "source": r.source,
                "target": r.target,
                "status": r.status.value,
                "detail": r.detail,
                "passed": r.passed,
            }
            for r in results
        ],
        "summary": {
            "total": len(results),
            "passed": sum(1 for r in results if r.passed),
            "failed": sum(1 for r in results if not r.passed),
        },
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def to_markdown(results: list[CheckResult], *, org_repo: str = "<source-repo>") -> str:
    """Markdown table for GITHUB_STEP_SUMMARY or PR comment fallbacks."""
    lines: list[str] = []
    lines.append("## Org baseline check")
    lines.append("")
    lines.append("| File | Status | Notes |")
    lines.append("| --- | --- | --- |")
    for r in results:
        glyph = _STATUS_GLYPH[r.status]
        notes = r.detail if r.detail else ""
        lines.append(f"| `{r.target}` | {glyph} {r.status.value} | {notes} |")
    lines.append("")
    failed = sum(1 for r in results if not r.passed)
    if failed:
        lines.append(f"**Verdict**: ❌ {failed} file(s) diverge from `{org_repo}`. Merge blocked.")
    else:
        lines.append(f"**Verdict**: ✅ all baseline files match `{org_repo}`.")
    return "\n".join(lines)


def to_check_run_payload(
    results: list[CheckResult],
    *,
    head_sha: str,
    name: str = "org-baseline / verify",
) -> dict[str, Any]:
    """Build the request body for POST /repos/{owner}/{repo}/check-runs."""
    failed = [r for r in results if not r.passed]
    conclusion = "failure" if failed else "success"

    annotations: list[dict[str, Any]] = []
    for r in failed:
        annotations.append(
            {
                "path": r.target,
                "start_line": 1,
                "end_line": 1,
                "annotation_level": "failure",
                "title": f"org-baseline: {r.status.value}",
                "message": r.detail or f"file diverges from canonical org/{r.source}",
            }
        )

    n_match = sum(1 for r in results if r.passed)
    n_drift = sum(1 for r in results if r.status is ResultStatus.DRIFT)
    n_missing = sum(1 for r in results if r.status is ResultStatus.MISSING)
    n_src_missing = sum(1 for r in results if r.status is ResultStatus.SOURCE_MISSING)
    summary_lines = [
        f"Compared {len(results)} files against `<source-repo>`.",
        f"- ✅ {n_match} match",
        f"- ❌ {n_drift} drift",
        f"- ⚠️ {n_missing} missing",
        f"- 🛑 {n_src_missing} source-missing (manifest bug)",
    ]
    summary = "\n".join(summary_lines)

    title = (
        "All baseline files match canonical."
        if conclusion == "success"
        else f"{len(failed)} file(s) diverge from canonical."
    )

    return {
        "name": name,
        "head_sha": head_sha,
        "status": "completed",
        "conclusion": conclusion,
        "output": {
            "title": title,
            "summary": summary,
            # GitHub allows up to 50 annotations per Check Run request; if more,
            # they need to be batched. For our manifest size (~5 entries) this
            # is never reached.
            "annotations": annotations,
        },
    }

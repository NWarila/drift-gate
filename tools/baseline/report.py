"""Output formatters.

Three formats:
  - JSON              — machine-readable; for piping to other tools.
  - Markdown          — human-readable; written to GITHUB_STEP_SUMMARY.
  - Check Runs API    — submitted to GitHub for inline annotations on
                        the offending files in the PR's "Files changed" view.

All three are fed by the same list[CheckResult]; presentation details
(linking back to source repo, embedding the diff inline, footer with
the SHA pin etc.) live here so check.py stays pure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .check import CheckResult, ResultStatus

_STATUS_GLYPH = {
    ResultStatus.MATCH: "✅",
    ResultStatus.DRIFT: "❌",
    ResultStatus.MISSING: "⚠️",
    ResultStatus.SOURCE_MISSING: "🛑",
}

# GitHub's Check Runs API limits annotations[]/text-fields. Cap raw_details
# on each annotation to keep us safely under the per-request 64KB cap.
_MAX_RAW_DETAILS_CHARS = 60_000


@dataclass(frozen=True)
class ReportContext:
    """Everything the formatters need beyond the raw results.

    All fields are optional — the formatters degrade gracefully when they
    aren't available (e.g. running locally with no GitHub context).
    """

    source_repo: str | None = None  # e.g. "nwarila-platform/.github"
    source_ref: str | None = None  # e.g. "f4dbbf9..."
    consumer_repo: str | None = None  # e.g. "nwarila-platform/github-terraform-framework"
    consumer_ref: str | None = None  # PR head SHA
    gate_version: str | None = None  # e.g. "973c3a9..."

    def short(self, ref: str | None) -> str:
        """Truncate a SHA-ish ref for compact display."""
        if not ref:
            return "<unknown>"
        if len(ref) >= 40 and all(c in "0123456789abcdef" for c in ref.lower()):
            return ref[:7]
        return ref


def _stats(results: list[CheckResult]) -> dict[str, int]:
    return {
        "total": len(results),
        "match": sum(1 for r in results if r.status is ResultStatus.MATCH),
        "drift": sum(1 for r in results if r.status is ResultStatus.DRIFT),
        "missing": sum(1 for r in results if r.status is ResultStatus.MISSING),
        "source_missing": sum(1 for r in results if r.status is ResultStatus.SOURCE_MISSING),
        "failed": sum(1 for r in results if not r.passed),
    }


# -------- JSON --------


def to_json(results: list[CheckResult], *, ctx: ReportContext | None = None) -> str:
    """Stable JSON output suitable for diff and piping."""
    ctx = ctx or ReportContext()
    s = _stats(results)
    payload = {
        "context": {
            "source_repo": ctx.source_repo,
            "source_ref": ctx.source_ref,
            "consumer_repo": ctx.consumer_repo,
            "consumer_ref": ctx.consumer_ref,
            "gate_version": ctx.gate_version,
        },
        "results": [
            {
                "source": r.source,
                "target": r.target,
                "status": r.status.value,
                "detail": r.detail,
                "passed": r.passed,
                "first_diff_line": r.first_diff_line,
                "diff": r.diff,
            }
            for r in results
        ],
        "summary": {
            "total": s["total"],
            "passed": s["match"],
            "failed": s["failed"],
            "by_status": {
                "match": s["match"],
                "drift": s["drift"],
                "missing": s["missing"],
                "source_missing": s["source_missing"],
            },
        },
    }
    return json.dumps(payload, indent=2, sort_keys=True)


# -------- Markdown (GITHUB_STEP_SUMMARY) --------


def _source_link(ctx: ReportContext, path: str) -> str:
    """Markdown link to a file in the source repo at source_ref, if known."""
    if not ctx.source_repo or not ctx.source_ref:
        return f"`{path}`"
    return f"[`{path}`](https://github.com/{ctx.source_repo}/blob/{ctx.source_ref}/{path})"


def _consumer_link(ctx: ReportContext, path: str) -> str:
    """Markdown link to a file in the consumer at consumer_ref, if known."""
    if not ctx.consumer_repo or not ctx.consumer_ref:
        return f"`{path}`"
    return f"[`{path}`](https://github.com/{ctx.consumer_repo}/blob/{ctx.consumer_ref}/{path})"


def to_markdown(results: list[CheckResult], *, ctx: ReportContext | None = None) -> str:
    """Polished markdown for GITHUB_STEP_SUMMARY / PR comment fallbacks.

    Layout:
      - Banner: GitHub admonition (NOTE for pass / CAUTION for fail) with verdict.
      - Stats table: counts by status.
      - Per-file results table with source + target as live links.
      - Per-DRIFT <details> block containing the unified diff in a ```diff fence.
      - Footer: source pin, consumer head, drift-gate version.
    """
    ctx = ctx or ReportContext()
    s = _stats(results)
    src_label = ctx.source_repo or "<source-repo>"
    src_short = ctx.short(ctx.source_ref)
    src_pin = f"`{src_label}@{src_short}`" if ctx.source_repo else "the canonical source"

    lines: list[str] = []
    lines.append("## Drift gate — org baseline")
    lines.append("")

    # --- Banner ---
    if s["failed"] == 0:
        lines.append("> [!NOTE]")
        lines.append(f"> ✅ **All {s['total']} baseline files match {src_pin}.**")
    else:
        lines.append("> [!CAUTION]")
        lines.append(
            f"> ❌ **{s['failed']} of {s['total']} files diverge from {src_pin}.** "
            f"Merge is blocked until every entry returns to byte-equality."
        )
    lines.append("")

    # --- Stats table ---
    lines.append("| Match | Drift | Missing | Source-missing | Total |")
    lines.append("| ---: | ---: | ---: | ---: | ---: |")
    lines.append(
        f"| ✅ {s['match']} "
        f"| ❌ {s['drift']} "
        f"| ⚠️ {s['missing']} "
        f"| 🛑 {s['source_missing']} "
        f"| **{s['total']}** |"
    )
    lines.append("")

    # --- Per-file results table ---
    lines.append("| Status | Consumer file | Canonical source | Notes |")
    lines.append("| --- | --- | --- | --- |")
    for r in results:
        glyph = _STATUS_GLYPH[r.status]
        target_md = _consumer_link(ctx, r.target)
        source_md = _source_link(ctx, r.source)
        notes = r.detail or ""
        lines.append(f"| {glyph} {r.status.value} | {target_md} | {source_md} | {notes} |")
    lines.append("")

    # --- Per-drift unified-diff blocks ---
    drifted = [r for r in results if r.status is ResultStatus.DRIFT and r.diff]
    if drifted:
        lines.append("### Diffs")
        lines.append("")
        for r in drifted:
            line_hint = f" (first diff at line {r.first_diff_line})" if r.first_diff_line else ""
            lines.append(f"<details><summary><code>{r.target}</code>{line_hint}</summary>")
            lines.append("")
            lines.append("```diff")
            # The diff already ends with newlines from unified_diff; strip a
            # trailing one so we don't get an extra blank line in the fence.
            lines.append(r.diff.rstrip("\n"))
            lines.append("```")
            lines.append("")
            lines.append("</details>")
            lines.append("")

    # --- How-to-fix ---
    if s["failed"]:
        lines.append("### How to fix")
        lines.append("")
        lines.append(
            f"Each non-matching file must be made byte-identical to its "
            f"canonical copy in {src_pin}. Easiest path: clone the source "
            f"repo at the pinned ref and copy over the canonical files."
        )
        lines.append("")
        if ctx.source_repo and ctx.source_ref:
            lines.append("```sh")
            lines.append(
                f"gh repo clone {ctx.source_repo} /tmp/source -- "
                f"--branch {ctx.source_ref} --depth 1"
            )
            for r in results:
                if r.status is ResultStatus.MATCH:
                    continue
                lines.append(f"cp /tmp/source/{r.source} {r.target}")
            lines.append("```")
            lines.append("")

    # --- Footer ---
    lines.append("---")
    footer_parts: list[str] = []
    if ctx.source_repo:
        footer_parts.append(f"**Compared against** {src_pin}")
    if ctx.consumer_ref:
        footer_parts.append(f"**Consumer @** `{ctx.short(ctx.consumer_ref)}`")
    if ctx.gate_version:
        gate_label = (
            f"[`NWarila/drift-gate@{ctx.short(ctx.gate_version)}`]"
            f"(https://github.com/NWarila/drift-gate/tree/{ctx.gate_version})"
        )
        footer_parts.append(f"**Engine** {gate_label}")
    if footer_parts:
        lines.append(" · ".join(footer_parts))

    return "\n".join(lines)


# -------- Check Runs API payload --------


def _annotation_for(r: CheckResult) -> dict[str, Any]:
    """Build one Check Run annotation for a non-passing result."""
    line = r.first_diff_line or 1
    if r.status is ResultStatus.DRIFT:
        if r.diff:
            title = f"DRIFT: {r.detail or 'content differs from canonical'}"
            raw = r.diff
        else:
            title = "DRIFT: binary file differs from canonical"
            raw = r.detail or ""
    elif r.status is ResultStatus.MISSING:
        title = "MISSING: file required by manifest is absent in consumer"
        raw = r.detail or ""
    elif r.status is ResultStatus.SOURCE_MISSING:
        title = "SOURCE_MISSING: manifest entry's source not found (manifest bug)"
        raw = r.detail or ""
    else:  # pragma: no cover — only called for non-passing results.
        title = r.status.value
        raw = r.detail or ""

    if len(raw) > _MAX_RAW_DETAILS_CHARS:
        raw = raw[:_MAX_RAW_DETAILS_CHARS] + "\n... [truncated]"

    return {
        "path": r.target,
        "start_line": line,
        "end_line": line,
        "annotation_level": "failure",
        "title": title,
        "message": r.detail or f"file diverges from canonical source/{r.source}",
        "raw_details": raw,
    }


def to_check_run_payload(
    results: list[CheckResult],
    *,
    head_sha: str,
    name: str = "drift-gate / verify",
    ctx: ReportContext | None = None,
) -> dict[str, Any]:
    """Build the request body for POST /repos/{owner}/{repo}/check-runs.

    The Check Run will display:
      - title:   e.g. "All 3 baseline files match canonical"
      - summary: stats table + footer with source pin + gate version
      - annotations[]: per non-passing file, anchored at the first
                       differing line, with the unified diff in raw_details.
    """
    ctx = ctx or ReportContext()
    s = _stats(results)
    failed = [r for r in results if not r.passed]
    conclusion = "failure" if failed else "success"

    if conclusion == "success":
        title = f"All {s['total']} baseline files match canonical."
    else:
        title = f"{s['failed']} of {s['total']} files diverge from canonical."

    src_label = ctx.source_repo or "<source-repo>"
    src_short = ctx.short(ctx.source_ref)
    src_pin = f"`{src_label}@{src_short}`" if ctx.source_repo else "the canonical source"

    summary_lines: list[str] = []
    summary_lines.append(f"Compared {s['total']} files against {src_pin}.")
    summary_lines.append("")
    summary_lines.append("| Match | Drift | Missing | Source-missing |")
    summary_lines.append("| ---: | ---: | ---: | ---: |")
    summary_lines.append(
        f"| ✅ {s['match']} | ❌ {s['drift']} | ⚠️ {s['missing']} | 🛑 {s['source_missing']} |"
    )
    summary_lines.append("")
    if ctx.gate_version:
        summary_lines.append(
            f"Engine: [`NWarila/drift-gate@{ctx.short(ctx.gate_version)}`]"
            f"(https://github.com/NWarila/drift-gate/tree/{ctx.gate_version})."
        )

    return {
        "name": name,
        "head_sha": head_sha,
        "status": "completed",
        "conclusion": conclusion,
        "output": {
            "title": title,
            "summary": "\n".join(summary_lines),
            # GitHub allows up to 50 annotations per Check Run request; we
            # have at most one per non-passing manifest entry, so for
            # realistic manifests we are nowhere near the cap.
            "annotations": [_annotation_for(r) for r in failed],
        },
    }

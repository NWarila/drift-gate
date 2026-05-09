"""Pure compare logic.

Given a manifest, a source root, and a consumer root, produce per-file
results (MATCH / DRIFT / MISSING / SOURCE_MISSING). For DRIFT we also
compute a unified diff and the first differing line so renderers can
present them inline. Side-effect-free — output formatting lives in
report.py.
"""

from __future__ import annotations

import difflib
import enum
from dataclasses import dataclass
from pathlib import Path

from .manifest import BaselineFile, BaselineManifest

# Cap the unified diff at this many lines. GitHub Check Run annotations
# allow ~64KB in raw_details; we want to leave room for headers + framing
# and we want the rendered <details> block to stay readable.
_MAX_DIFF_LINES = 80


class ResultStatus(str, enum.Enum):
    MATCH = "MATCH"
    DRIFT = "DRIFT"
    MISSING = "MISSING"
    SOURCE_MISSING = "SOURCE_MISSING"


@dataclass(frozen=True)
class CheckResult:
    """Per-file comparison result."""

    source: str
    target: str
    status: ResultStatus
    detail: str = ""
    # Unified diff text — populated only on DRIFT for utf-8-decodable files.
    # For binary drift we leave this None and put a one-liner in detail.
    diff: str | None = None
    # 1-indexed line number in the target where drift first appears.
    # 1 for binary drift or whole-file replacement; None for non-DRIFT.
    first_diff_line: int | None = None

    @property
    def passed(self) -> bool:
        return self.status is ResultStatus.MATCH


def _compute_text_diff(
    source_text: str, target_text: str, *, source_label: str, target_label: str
) -> tuple[str, int]:
    """Return (truncated unified-diff string, 1-indexed first differing line in target).

    The first-differing-line is reported in the *target* file's coordinate
    system because that's what the inline annotation will pin against.
    """
    src_lines = source_text.splitlines(keepends=True)
    tgt_lines = target_text.splitlines(keepends=True)

    # Find first differing target line via SequenceMatcher's first non-equal opcode.
    matcher = difflib.SequenceMatcher(a=src_lines, b=tgt_lines, autojunk=False)
    first_line = 1
    for tag, _i1, _i2, j1, _j2 in matcher.get_opcodes():
        if tag != "equal":
            # j1 is 0-indexed into target lines; convert to 1-indexed.
            # When the target is a strict prefix of source (deletion at end),
            # j1 == len(tgt_lines) and 1-indexed line is len(tgt_lines) which
            # may be 0 — clamp to 1.
            first_line = max(1, j1 + 1)
            break

    diff_iter = difflib.unified_diff(
        src_lines,
        tgt_lines,
        fromfile=source_label,
        tofile=target_label,
        n=3,
    )
    diff_lines = list(diff_iter)

    if len(diff_lines) > _MAX_DIFF_LINES:
        kept = diff_lines[:_MAX_DIFF_LINES]
        omitted = len(diff_lines) - _MAX_DIFF_LINES
        kept.append(f"... [{omitted} more line(s) omitted]\n")
        diff_lines = kept

    return "".join(diff_lines), first_line


def compare_file(
    source_root: Path,
    consumer_root: Path,
    entry: BaselineFile,
) -> CheckResult:
    """Compare one manifest entry. Pure function (only reads the two files)."""
    src = source_root / entry.source
    tgt = consumer_root / entry.target

    if not src.is_file():
        return CheckResult(
            source=entry.source,
            target=entry.target,
            status=ResultStatus.SOURCE_MISSING,
            detail=f"canonical source not found at {entry.source} in source repo",
        )
    if not tgt.is_file():
        return CheckResult(
            source=entry.source,
            target=entry.target,
            status=ResultStatus.MISSING,
            detail=f"file does not exist in consumer; copy from source/{entry.source}",
        )

    src_bytes = src.read_bytes()
    tgt_bytes = tgt.read_bytes()
    if src_bytes == tgt_bytes:
        return CheckResult(
            source=entry.source,
            target=entry.target,
            status=ResultStatus.MATCH,
        )

    # Drift. Try to render a unified diff if both sides decode as utf-8;
    # otherwise fall back to a binary one-liner.
    try:
        src_text = src_bytes.decode("utf-8")
        tgt_text = tgt_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return CheckResult(
            source=entry.source,
            target=entry.target,
            status=ResultStatus.DRIFT,
            detail=(
                f"binary file differs ({len(src_bytes)} bytes canonical "
                f"vs {len(tgt_bytes)} bytes consumer)"
            ),
            first_diff_line=1,
        )

    diff_text, first_line = _compute_text_diff(
        src_text,
        tgt_text,
        source_label=f"a/{entry.source}",
        target_label=f"b/{entry.target}",
    )
    n_added = sum(
        1 for ln in diff_text.splitlines() if ln.startswith("+") and not ln.startswith("+++")
    )
    n_removed = sum(
        1 for ln in diff_text.splitlines() if ln.startswith("-") and not ln.startswith("---")
    )
    return CheckResult(
        source=entry.source,
        target=entry.target,
        status=ResultStatus.DRIFT,
        detail=f"content differs from canonical (+{n_added} -{n_removed} lines)",
        diff=diff_text,
        first_diff_line=first_line,
    )


def run_check(
    manifest: BaselineManifest,
    source_root: Path,
    consumer_root: Path,
) -> list[CheckResult]:
    """Run the full check. Returns one result per manifest entry."""
    return [compare_file(source_root, consumer_root, entry) for entry in manifest.files]


def overall_passed(results: list[CheckResult]) -> bool:
    """True iff every result is MATCH."""
    return all(r.passed for r in results)

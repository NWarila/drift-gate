"""Pure compare logic.

Given a manifest, an org root, and a consumer root, produce per-file results
indicating MATCH / DRIFT / MISSING / SOURCE_MISSING. Side-effect-free — output
formatting (JSON, markdown, Check Runs API) lives elsewhere.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from pathlib import Path

from .manifest import BaselineFile, BaselineManifest


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

    @property
    def passed(self) -> bool:
        return self.status is ResultStatus.MATCH


def compare_file(
    org_root: Path,
    consumer_root: Path,
    entry: BaselineFile,
) -> CheckResult:
    """Compare one manifest entry. Pure function: no I/O outside the two reads."""
    src = org_root / entry.source
    tgt = consumer_root / entry.target

    if not src.is_file():
        return CheckResult(
            source=entry.source,
            target=entry.target,
            status=ResultStatus.SOURCE_MISSING,
            detail=f"canonical source not found at org/{entry.source}",
        )
    if not tgt.is_file():
        return CheckResult(
            source=entry.source,
            target=entry.target,
            status=ResultStatus.MISSING,
            detail=f"file does not exist in consumer; copy from <org>/.github/{entry.source}",
        )
    if src.read_bytes() != tgt.read_bytes():
        return CheckResult(
            source=entry.source,
            target=entry.target,
            status=ResultStatus.DRIFT,
            detail=f"content differs from <org>/.github/{entry.source} (manual edit?)",
        )
    return CheckResult(
        source=entry.source,
        target=entry.target,
        status=ResultStatus.MATCH,
    )


def run_check(
    manifest: BaselineManifest,
    org_root: Path,
    consumer_root: Path,
) -> list[CheckResult]:
    """Run the full check. Returns one result per manifest entry."""
    return [compare_file(org_root, consumer_root, entry) for entry in manifest.files]


def overall_passed(results: list[CheckResult]) -> bool:
    """True iff every result is MATCH."""
    return all(r.passed for r in results)

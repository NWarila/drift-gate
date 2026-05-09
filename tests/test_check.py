"""End-to-end tests for the compare logic + report formatters against fixtures."""

from __future__ import annotations

import json
import pathlib

from baseline.check import ResultStatus, compare_file, overall_passed, run_check
from baseline.manifest import BaselineFile, load_manifest
from baseline.report import (
    ReportContext,
    to_check_run_payload,
    to_json,
    to_markdown,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
SOURCE = FIXTURES / "source"
GOOD = FIXTURES / "good-consumer"
BAD = FIXTURES / "bad-consumer"


def _manifest():
    return load_manifest(SOURCE / "baseline-manifest.json")


# -------- check.py: pure compare logic --------


def test_good_consumer_all_match():
    results = run_check(_manifest(), SOURCE, GOOD)
    assert all(r.status is ResultStatus.MATCH for r in results), [
        (r.target, r.status) for r in results
    ]
    assert overall_passed(results)
    # MATCH results carry no diff or line hint.
    for r in results:
        assert r.diff is None
        assert r.first_diff_line is None


def test_bad_consumer_detects_drift_and_missing():
    results = run_check(_manifest(), SOURCE, BAD)
    statuses = {r.target: r.status for r in results}
    assert statuses == {
        "alpha.md": ResultStatus.MATCH,
        "beta.md": ResultStatus.DRIFT,
        "gamma.md": ResultStatus.MISSING,
    }
    assert not overall_passed(results)


def test_drift_result_carries_unified_diff_and_first_line():
    results = run_check(_manifest(), SOURCE, BAD)
    drift = next(r for r in results if r.target == "beta.md")
    assert drift.status is ResultStatus.DRIFT
    assert drift.diff is not None and drift.diff != ""
    # Unified-diff hallmarks.
    assert drift.diff.startswith("---") or drift.diff.startswith("--- ")
    assert "+++" in drift.diff
    assert "@@" in drift.diff
    # The bad-consumer/beta.md mutates the first content line, so first
    # differing target line is at or near 1.
    assert drift.first_diff_line is not None
    assert drift.first_diff_line >= 1
    # Detail summarises the +/- counts.
    assert "+" in drift.detail and "-" in drift.detail


def test_binary_drift_falls_back_to_byte_count_message(tmp_path):
    """Binary files (non-utf-8) drift without a unified diff."""
    src_root = tmp_path / "source"
    cons_root = tmp_path / "consumer"
    src_root.mkdir()
    cons_root.mkdir()
    (src_root / "blob.bin").write_bytes(b"\xff\xfe\x00abc")
    (cons_root / "blob.bin").write_bytes(b"\xff\xfe\x00xyz")
    entry = BaselineFile(source="blob.bin", target="blob.bin")
    r = compare_file(src_root, cons_root, entry)
    assert r.status is ResultStatus.DRIFT
    assert r.diff is None
    assert r.first_diff_line == 1
    assert "binary file differs" in r.detail


def test_drift_diff_truncates_for_large_changes(tmp_path):
    """Very large drifts get truncated with an explicit marker."""
    src_root = tmp_path / "source"
    cons_root = tmp_path / "consumer"
    src_root.mkdir()
    cons_root.mkdir()
    src_lines = "\n".join(f"src-line-{i}" for i in range(500)) + "\n"
    tgt_lines = "\n".join(f"tgt-line-{i}" for i in range(500)) + "\n"
    (src_root / "huge.txt").write_text(src_lines, encoding="utf-8")
    (cons_root / "huge.txt").write_text(tgt_lines, encoding="utf-8")
    entry = BaselineFile(source="huge.txt", target="huge.txt")
    r = compare_file(src_root, cons_root, entry)
    assert r.status is ResultStatus.DRIFT
    assert r.diff is not None
    assert "more line(s) omitted" in r.diff
    # Truncation cap is 80 lines; output should be roughly that plus the
    # truncation footer line, never anywhere near the 1000 raw lines.
    assert r.diff.count("\n") <= 90


# -------- report.py: JSON --------


def test_json_output_is_stable():
    results = run_check(_manifest(), SOURCE, GOOD)
    parsed = json.loads(to_json(results))
    assert parsed["summary"]["total"] == len(results)
    assert parsed["summary"]["passed"] == len(results)
    assert parsed["summary"]["failed"] == 0
    # Context block exists even when empty.
    assert "context" in parsed
    # by_status surfaces all four buckets.
    assert set(parsed["summary"]["by_status"]) == {
        "match",
        "drift",
        "missing",
        "source_missing",
    }


def test_json_output_includes_diff_for_drift():
    results = run_check(_manifest(), SOURCE, BAD)
    parsed = json.loads(to_json(results))
    drift_entry = next(e for e in parsed["results"] if e["target"] == "beta.md")
    assert drift_entry["diff"] is not None
    assert "@@" in drift_entry["diff"]
    assert drift_entry["first_diff_line"] is not None


# -------- report.py: Markdown --------


def test_markdown_pass_uses_note_banner():
    results = run_check(_manifest(), SOURCE, GOOD)
    md = to_markdown(results)
    assert "[!NOTE]" in md
    assert "[!CAUTION]" not in md
    assert "✅" in md


def test_markdown_fail_uses_caution_banner_and_lists_drifts():
    results = run_check(_manifest(), SOURCE, BAD)
    md = to_markdown(results)
    assert "[!CAUTION]" in md
    assert "Merge is blocked" in md
    # Each target appears as a code-fenced filename in the table.
    for r in results:
        assert f"`{r.target}`" in md
    # The drift's unified diff is embedded under a <details> block.
    assert "<details>" in md
    assert "```diff" in md
    # How-to-fix section appears on failure.
    assert "How to fix" in md


def test_markdown_with_full_context_renders_links_and_footer():
    results = run_check(_manifest(), SOURCE, BAD)
    ctx = ReportContext(
        source_repo="nwarila-platform/.github",
        source_ref="f4dbbf97c5f11b96b9db167242955c51ad847391",
        consumer_repo="nwarila-platform/foo",
        consumer_ref="0" * 40,
        gate_version="973c3a9e4cee3000118e39a0cc9014eb6f4972a1",
    )
    md = to_markdown(results, ctx=ctx)
    # Source repo + ref shows up in the banner / footer pin.
    assert "nwarila-platform/.github@f4dbbf9" in md
    # Source link points at the canonical file at the pinned ref.
    assert "https://github.com/nwarila-platform/.github/blob/" in md
    # Consumer link points at the file at consumer head.
    assert "https://github.com/nwarila-platform/foo/blob/" in md
    # Footer mentions the drift-gate engine, linked.
    assert "NWarila/drift-gate@973c3a9" in md
    # How-to-fix snippet uses the source pin.
    assert "gh repo clone nwarila-platform/.github" in md


# -------- report.py: Check Runs API --------


def test_check_run_payload_failure_has_per_file_annotations():
    results = run_check(_manifest(), SOURCE, BAD)
    payload = to_check_run_payload(results, head_sha="0" * 40)
    assert payload["conclusion"] == "failure"
    failing_targets = {r.target for r in results if not r.passed}
    annotation_paths = {a["path"] for a in payload["output"]["annotations"]}
    assert annotation_paths == failing_targets


def test_check_run_payload_success_has_no_annotations():
    results = run_check(_manifest(), SOURCE, GOOD)
    payload = to_check_run_payload(results, head_sha="0" * 40)
    assert payload["conclusion"] == "success"
    assert payload["output"]["annotations"] == []


def test_check_run_drift_annotation_anchors_first_diff_line():
    results = run_check(_manifest(), SOURCE, BAD)
    payload = to_check_run_payload(results, head_sha="0" * 40)
    drift_ann = next(a for a in payload["output"]["annotations"] if a["path"] == "beta.md")
    drift_result = next(r for r in results if r.target == "beta.md")
    assert drift_ann["start_line"] == drift_result.first_diff_line
    assert drift_ann["end_line"] == drift_result.first_diff_line
    assert drift_ann["annotation_level"] == "failure"


def test_check_run_drift_annotation_carries_unified_diff_in_raw_details():
    results = run_check(_manifest(), SOURCE, BAD)
    payload = to_check_run_payload(results, head_sha="0" * 40)
    drift_ann = next(a for a in payload["output"]["annotations"] if a["path"] == "beta.md")
    raw = drift_ann["raw_details"]
    assert "@@" in raw
    assert raw.startswith("---") or raw.startswith("--- ")


def test_check_run_summary_uses_source_pin_and_engine_link():
    results = run_check(_manifest(), SOURCE, BAD)
    ctx = ReportContext(
        source_repo="nwarila-platform/.github",
        source_ref="f4dbbf97c5f11b96b9db167242955c51ad847391",
        gate_version="973c3a9e4cee3000118e39a0cc9014eb6f4972a1",
    )
    payload = to_check_run_payload(
        results, head_sha="0" * 40, ctx=ctx, name="org-baseline / verify"
    )
    summary = payload["output"]["summary"]
    assert "nwarila-platform/.github@f4dbbf9" in summary
    assert "NWarila/drift-gate@973c3a9" in summary
    assert payload["name"] == "org-baseline / verify"

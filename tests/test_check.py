"""End-to-end tests for the compare logic against fixture consumer repos."""

from __future__ import annotations

import json
import pathlib

from baseline.check import ResultStatus, overall_passed, run_check
from baseline.manifest import load_manifest
from baseline.report import to_check_run_payload, to_json, to_markdown

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
SOURCE = FIXTURES / "source"
GOOD = FIXTURES / "good-consumer"
BAD = FIXTURES / "bad-consumer"


def _manifest():
    return load_manifest(SOURCE / "baseline-manifest.json")


def test_good_consumer_all_match():
    results = run_check(_manifest(), SOURCE, GOOD)
    assert all(r.status is ResultStatus.MATCH for r in results), [
        (r.target, r.status) for r in results
    ]
    assert overall_passed(results)


def test_bad_consumer_detects_drift_and_missing():
    results = run_check(_manifest(), SOURCE, BAD)
    statuses = {r.target: r.status for r in results}
    # The bad consumer has:
    #  - one MATCH (alpha.md untouched)
    #  - one DRIFT (beta.md content differs)
    #  - one MISSING (gamma.md absent)
    assert statuses == {
        "alpha.md": ResultStatus.MATCH,
        "beta.md": ResultStatus.DRIFT,
        "gamma.md": ResultStatus.MISSING,
    }
    assert not overall_passed(results)


def test_json_output_is_stable():
    results = run_check(_manifest(), SOURCE, GOOD)
    parsed = json.loads(to_json(results))
    assert parsed["summary"]["total"] == len(results)
    assert parsed["summary"]["passed"] == len(results)
    assert parsed["summary"]["failed"] == 0


def test_markdown_output_contains_each_target():
    results = run_check(_manifest(), SOURCE, BAD)
    md = to_markdown(results)
    for r in results:
        assert f"`{r.target}`" in md
    assert "Merge blocked" in md


def test_check_run_payload_failure():
    results = run_check(_manifest(), SOURCE, BAD)
    payload = to_check_run_payload(results, head_sha="0" * 40)
    assert payload["conclusion"] == "failure"
    # Annotations should exist for each non-passing file.
    failing_targets = {r.target for r in results if not r.passed}
    annotation_paths = {a["path"] for a in payload["output"]["annotations"]}
    assert annotation_paths == failing_targets


def test_check_run_payload_success():
    results = run_check(_manifest(), SOURCE, GOOD)
    payload = to_check_run_payload(results, head_sha="0" * 40)
    assert payload["conclusion"] == "success"
    assert payload["output"]["annotations"] == []
